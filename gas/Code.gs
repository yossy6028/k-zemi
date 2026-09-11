/**
 * Kゼミ中野校 問合せフォーム受信エンドポイント（Google Apps Script Web App）
 *
 * FormSubmit.co 障害（2026-07-10 HTTP 522 全面ダウン）を受けた恒久移行先。
 * フォーム（https://k-zemi.net/#contact-form）からの POST を受け、
 * 塾長宛メールに変換して送信する。
 *
 * デプロイ: Web App / 実行ユーザー=自分 / アクセス=全員（匿名含む）
 */

var DEST_EMAIL = 'nakano@kzemi.com';
var SUBJECT = '【Kゼミ中野校】無料体験授業 お申込み';
var THANKS_URL = 'https://k-zemi.net/thanks.html';
var FIELD_ORDER = ['生徒氏名', '保護者氏名', '学年', '学校名', '電話番号', 'メールアドレス', '相談内容・ご質問', '紹介者'];

function doPost(e) {
  var p = parseFormBody(e);

  // ハニーポット: bot には成功を装って何もしない
  if (p._honey) {
    return jsonOut({ success: 'true' });
  }

  // 必須項目チェック（フォーム側の required と同一の6項目で二重防御）
  var required = ['生徒氏名', '保護者氏名', '学年', '学校名', '電話番号', 'メールアドレス'];
  var missing = required.filter(function (k) { return !p[k]; });
  if (missing.length) {
    return jsonOut({ success: 'false', message: 'required fields missing', missing: missing });
  }

  // 各フィールドを1000文字に制限（巨大ボディによるメール肥大の防止）
  FIELD_ORDER.forEach(function (label) {
    if (p[label] && p[label].length > 1000) p[label] = p[label].slice(0, 1000) + '…（文字数上限で切り詰め）';
  });

  var mailOptions = { name: 'Kゼミ中野校 ホームページ' };
  // 返信ボタンで保護者へ直接返信できるようにする（不正な値なら replyTo なしで送る）
  try {
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(p['メールアドレス'])) {
      mailOptions.replyTo = p['メールアドレス'];
    }
  } catch (err) {}

  // ここから先（レート判定→台帳追記→メール送信→状態更新）はロック1本で完全直列化する。
  // ロックが取れない場合は処理せず success:false を返し、正規ユーザーは
  // フォールバック（メール/電話導線）で連絡できるため、安全側（フェイルクローズ）に倒せる
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(8000);
  } catch (err) {
    return jsonOut({ success: 'false', message: 'busy' });
  }

  try {
    // レート制限: 10分15件 + 日次50件（スパムによるGmailクォータ枯渇・受信箱洪水の防止）
    if (!checkRateLimit()) {
      return jsonOut({ success: 'false', message: 'rate limited' });
    }

    // メール送信より先に台帳へ記録する（送信失敗しても問合せ自体は必ず残る）
    var ledgerRow = 0;
    try {
      ledgerRow = appendToLedger(p, 'メール送信前');
    } catch (err) {
      // 台帳失敗はメール送信を止めないが、静かに握りつぶさずメール本文で知らせる
    }

    var body = buildMailBody(p);
    if (!ledgerRow) {
      body = '※注意: 問合せ台帳（スプレッドシート）への記録に失敗しました。台帳の存在と権限を確認してください。\n\n' + body;
    }
    // MailApp を使う（GmailApp は Gmail 全体の読み書き削除スコープを要求するため。送信専用の script.send_mail で足りる）
    MailApp.sendEmail(DEST_EMAIL, SUBJECT, body, mailOptions);
    if (ledgerRow) {
      try { updateLedgerStatus(ledgerRow, 'メール送信済み'); } catch (err) {}
    }
  } finally {
    lock.releaseLock();
  }

  // fetch(AJAX) からは JSON、JS無効環境の直接POSTには thanks.html へ誘導する HTML を返す
  if (p._ajax) {
    return jsonOut({ success: 'true' });
  }
  return HtmlService.createHtmlOutput(
    '<meta http-equiv="refresh" content="0;url=' + THANKS_URL + '">' +
    '<p>送信ありがとうございました。<a href="' + THANKS_URL + '">こちら</a>に移動します。</p>'
  );
}

/**
 * 塾長が受け取るメール本文を組み立てる。
 * p にはフォームの入力値が入る（キーは FIELD_ORDER の日本語名）。
 * 未入力の任意項目（相談内容・紹介者）が空文字で来ることに注意。
 */
function buildMailBody(p) {
  var lines = ['ホームページの無料体験フォームからお申込みが届きました。', ''];
  FIELD_ORDER.forEach(function (label) {
    lines.push('■ ' + label + '：' + (p[label] ? p[label] : '（未記入）'));
  });
  lines.push('');
  lines.push('送信日時：' + Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd HH:mm'));
  lines.push('（このメールはフォーム送信システムから自動送信されています。返信すると保護者の方に直接届きます）');
  return lines.join('\n');
}

/**
 * GAS の e.parameter は日本語（非ASCII）のパラメータ名を正しくデコードできない
 * （キーが空文字になる）ため、application/x-www-form-urlencoded のボディを自前でパースする。
 * フォーム側は URLSearchParams で送信すること（multipart/form-data は不可）。
 */
function parseFormBody(e) {
  var raw = e && e.postData && e.postData.contents;
  var type = (e && e.postData && e.postData.type) || '';
  if (!raw || type.indexOf('form-urlencoded') === -1) {
    return (e && e.parameter) || {};
  }
  var out = {};
  raw.split('&').forEach(function (pair) {
    if (!pair) return;
    var i = pair.indexOf('=');
    var k = i < 0 ? pair : pair.slice(0, i);
    var v = i < 0 ? '' : pair.slice(i + 1);
    try { k = decodeURIComponent(k.replace(/\+/g, ' ')); } catch (err) { return; }
    try { v = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (err) { v = ''; }
    if (k) out[k] = v;
  });
  return out;
}

/**
 * 問合せ台帳スプレッドシート。初回送信時に自動作成し、IDをScript Propertiesに保存。
 * メール消失時のバックアップとして全問合せ（メールアドレス含む）をたどれるようにする。
 */
function getLedgerSheet() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('LEDGER_SPREADSHEET_ID');
  var ss;
  if (id) {
    ss = SpreadsheetApp.openById(id);
  } else {
    ss = SpreadsheetApp.create('Kゼミ問合せ台帳');
    props.setProperty('LEDGER_SPREADSHEET_ID', ss.getId());
    ss.getActiveSheet().appendRow(['受信日時'].concat(FIELD_ORDER).concat(['状態']));
  }
  return ss.getActiveSheet();
}

// 追記した行番号を返す（状態更新は必ずこの行番号を使い、並行送信時の別行誤更新を防ぐ）
function appendToLedger(p, status) {
  var sheet = getLedgerSheet();
  var row = [Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd HH:mm:ss')];
  FIELD_ORDER.forEach(function (label) { row.push(sanitizeCell(p[label] || '')); });
  row.push(status);
  sheet.appendRow(row);
  return sheet.getLastRow();
}

// 数式インジェクション対策: = + - @ で始まる値はSheetsが数式として評価しうるため
// 先頭にアポストロフィを付けて文字列扱いに固定する（表示上は見えない）
function sanitizeCell(v) {
  return /^[=+\-@]/.test(v) ? "'" + v : v;
}

// グローバルレート制限: 10分15件 + 1日50件（Gmailコンシューマ100通/日クォータの枯渇防止）。
// 必ず doPost のスクリプトロック内から呼ぶこと（呼び出し側で直列化済み）。
// 10分窓はCacheService、日次はCacheのTTL上限(6時間)では日を跨げないためPropertiesServiceで永続化。
// 例外はdoPost側に伝播させ、クライアントのフォールバック導線に落とす（フェイルクローズ）
function checkRateLimit() {
  var cache = CacheService.getScriptCache();
  var winKey = 'rate10m_' + Math.floor(new Date().getTime() / 600000);
  var w = Number(cache.get(winKey) || 0) + 1;
  cache.put(winKey, String(w), 700);
  if (w > 15) return false;

  var props = PropertiesService.getScriptProperties();
  var today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyyMMdd');
  var raw = props.getProperty('DAILY_COUNT');
  var d = null;
  try { d = raw ? JSON.parse(raw) : null; } catch (err) {}
  if (!d || d.date !== today) d = { date: today, count: 0 };
  d.count += 1;
  props.setProperty('DAILY_COUNT', JSON.stringify(d));
  return d.count <= 50;
}

function updateLedgerStatus(rowIndex, status) {
  var sheet = getLedgerSheet();
  if (rowIndex > 1) {
    sheet.getRange(rowIndex, FIELD_ORDER.length + 2).setValue(status);
  }
}

function jsonOut(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// 外形監視用の生存応答（公開情報はokフラグのみ。UptimeRobot等の外部監視にも転用可）
function doGet() {
  return jsonOut({ ok: 'true' });
}

/**
 * 定期ヘルスチェック（時間主導トリガーで6時間毎に実行）。
 * 異常時のみ管理者へメール通知する。通知は12時間に1回まで（アラート洪水防止）。
 */
var ADMIN_EMAIL = 'katsu.yoshii@gmail.com';
var PUBLIC_PAGE = 'https://k-zemi.net/';
var DEPLOY_ID_FRAGMENT = 'AKfycbybbskYZE8zn-RWmgmye1NlVBSFqdp1P9Gsl6mxZypN3OWutHA7kRHxmnUDiDnOEBX2FQ';

function fetchWithRetry_(url, tries, waitMs) {
  // 一過性ブリップ（GAS/Fastly側の瞬断）を障害と誤判定しないため、間隔を空けて再試行する。
  // 全試行が失敗したときだけ異常とみなす。observed には各試行の結果を残す（事後診断用）。
  var observed = [];
  var last = null;
  for (var i = 0; i < tries; i++) {
    if (i > 0) Utilities.sleep(waitMs);
    try {
      var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
      observed.push(String(res.getResponseCode()));
      last = { ok: true, res: res, code: res.getResponseCode() };
      if (res.getResponseCode() === 200) return { ok: true, res: res, code: 200, observed: observed };
    } catch (err) {
      observed.push('ERR:' + err);
      last = { ok: false, err: err, code: 0 };
    }
  }
  last.observed = observed;
  return last;
}

/**
 * Web Appエンドポイントの2段プローブ。
 * GASの /exec は「①/exec が doGet を実行し、結果を script.googleusercontent.com へ 302 転送 →
 * ②転送先(echoホスト)が本文を返す」という2段構造。①の302が得られた時点で
 * 「デプロイが存在し doGet が実行された」＝フォーム受信は生きている、が確定する。
 * ②は Google 側の都合で数分規模の 404/503 を返すことがあり（2026-07-19 503 / 08-19 404 / 09-11 404 は
 * いずれも実害なし）、フォーム受信とは無関係。単発リトライでは吸収できない長さのため、
 * 段ごとに結果を分けて返し、呼び出し側で通知方針を変える。
 */
function probeExec_(tries, waitMs) {
  var url = 'https://script.google.com/macros/s/' + DEPLOY_ID_FRAGMENT + '/exec';
  var observed = [];
  var hop1Ok = false;
  var detail = '';
  for (var i = 0; i < tries; i++) {
    if (i > 0) Utilities.sleep(waitMs);
    try {
      var r1 = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: false });
      var c1 = r1.getResponseCode();
      if (c1 === 200 && r1.getContentText().indexOf('"ok":"true"') !== -1) {
        observed.push('200');
        return { hop1Ok: true, e2eOk: true, observed: observed, detail: '' };
      }
      var loc = headerOf_(r1, 'Location');
      if ((c1 === 302 || c1 === 301 || c1 === 303) && loc.indexOf('script.googleusercontent.com') !== -1) {
        hop1Ok = true;
        var r2 = UrlFetchApp.fetch(loc, { muteHttpExceptions: true, followRedirects: true });
        var c2 = r2.getResponseCode();
        observed.push(c1 + '>' + c2);
        if (c2 === 200 && r2.getContentText().indexOf('"ok":"true"') !== -1) {
          return { hop1Ok: true, e2eOk: true, observed: observed, detail: '' };
        }
        detail = 'echo応答: ' + snippet_(r2.getContentText());
      } else {
        observed.push(String(c1) + (loc ? '>' + loc.replace(/\?.*$/, '') : ''));
        detail = '/exec応答: ' + snippet_(r1.getContentText());
      }
    } catch (err) {
      observed.push('ERR:' + err);
      detail = String(err);
    }
  }
  return { hop1Ok: hop1Ok, e2eOk: false, observed: observed, detail: detail };
}

function headerOf_(res, name) {
  var h = res.getAllHeaders();
  var v = h[name] || h[name.toLowerCase()] || '';
  return Array.isArray(v) ? String(v[0] || '') : String(v);
}

function snippet_(text) {
  return String(text || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 160);
}

function healthCheck() {
  var problems = [];

  // 1. 本番ページの生存と、フォーム送信先がGASのまま残っているか（先祖返り・巻き戻り検知）
  var r1 = fetchWithRetry_(PUBLIC_PAGE, 3, 15000);
  if (!r1.ok) {
    problems.push('本番ページの取得に失敗: ' + r1.err + '（3回試行: ' + r1.observed.join(', ') + '）');
  } else if (r1.code !== 200) {
    problems.push('本番ページ ' + PUBLIC_PAGE + ' が HTTP ' + r1.code + '（3回試行: ' + r1.observed.join(', ') + '）');
  } else if (r1.res.getContentText().indexOf(DEPLOY_ID_FRAGMENT) === -1) {
    problems.push('フォームの送信先(GAS URL)が本番ページから消えている（デプロイ巻き戻りの可能性）');
  }

  // 2. Web Appエンドポイント（2段プローブ）。①/exec の302すら得られない＝デプロイ消失・停止なので即通知。
  //    ①は通るが②(echoホスト)だけ失敗＝Google側の一過性事象。フォーム受信は生きているので
  //    2回連続（=12時間継続）した場合にのみ通知する。連続回数は Script Properties に保持。
  var props = PropertiesService.getScriptProperties();
  var r2 = probeExec_(3, 20000);
  if (!r2.hop1Ok) {
    problems.push('フォーム受信エンドポイント(/exec)が応答しない（3回試行: ' + r2.observed.join(', ') + '）' +
      (r2.detail ? ' ' + r2.detail : ''));
    props.deleteProperty('EXEC_E2E_FAIL_STREAK');
  } else if (!r2.e2eOk) {
    var streak = Number(props.getProperty('EXEC_E2E_FAIL_STREAK') || 0) + 1;
    props.setProperty('EXEC_E2E_FAIL_STREAK', String(streak));
    if (streak >= 2) {
      problems.push('エンドポイントは生存（/execは302転送を返す）だが、応答本文の取得が ' + streak +
        ' 回連続で失敗（今回の3回試行: ' + r2.observed.join(', ') + '）' + (r2.detail ? ' ' + r2.detail : '') +
        ' ※フォーム受信自体は生きている可能性が高い。台帳に新着がないか確認');
    }
  } else {
    props.deleteProperty('EXEC_E2E_FAIL_STREAK');
  }

  // 3. 台帳スプレッドシートにアクセスできるか（削除・権限剥奪の検知）
  try {
    getLedgerSheet().getLastRow();
  } catch (err) {
    problems.push('問合せ台帳にアクセスできない（削除/権限変更の可能性）: ' + err);
  }

  // 4. Gmail残クォータ（枯渇間近=スパム攻撃や大量送信の兆候）
  try {
    var quota = MailApp.getRemainingDailyQuota();
    if (quota < 20) problems.push('Gmail送信の残りクォータが ' + quota + ' 通（スパム攻撃の可能性。台帳と受信箱を確認）');
  } catch (err) {}

  if (!problems.length) return;

  // アラートは12時間に1回まで
  var last = Number(props.getProperty('LAST_HEALTH_ALERT') || 0);
  var now = new Date().getTime();
  if (now - last < 12 * 3600 * 1000) return;

  MailApp.sendEmail(ADMIN_EMAIL, '【要確認】Kゼミ問合せフォーム ヘルスチェック異常',
    'Kゼミ問合せフォームの定期チェック（6時間毎）で異常を検知しました。\n\n' +
    problems.map(function (s) { return '・' + s; }).join('\n') +
    '\n\n確認手順: https://k-zemi.net/ のフォームからテスト送信 → 台帳とnakano@kzemi.comへの着信を確認。' +
    '\nスクリプト: https://script.google.com/d/1I69zIFJUZDH9Z2UCI9IyGj_y17qZWuVQcEozVjV-NeZfh8_WeHvP7yFH/edit');

  // 送信が成功した後にだけラッチを立てる（先に立てると送信失敗時に12時間無音になる）
  props.setProperty('LAST_HEALTH_ALERT', String(now));
}

// 時間主導トリガー(6時間毎)を冪等に設置する（healthCheckトリガーが既にあれば何もしない）
function installHealthCheckTrigger() {
  var exists = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === 'healthCheck';
  });
  if (!exists) {
    ScriptApp.newTrigger('healthCheck').timeBased().everyHours(6).create();
  }
  return ScriptApp.getProjectTriggers().length;
}
