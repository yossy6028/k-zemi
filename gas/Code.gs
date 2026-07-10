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

  // レート制限: 10分あたり15件まで（スパムによるGmailクォータ枯渇・受信箱洪水の防止）。
  // 超過時は success:false を返し、正規ユーザーはフォールバック（メール/電話導線）で連絡できる
  if (!checkRateLimit()) {
    return jsonOut({ success: 'false', message: 'rate limited' });
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

  // 台帳の行位置ずれ防止（同時送信対策）。ロック不能でも送信は続行する
  var lock = LockService.getScriptLock();
  var locked = false;
  try { locked = lock.tryLock(10000); } catch (err) {}

  // メール送信より先に台帳へ記録する（送信失敗しても問合せ自体は必ず残る）
  var ledgerRow = 0;
  try {
    ledgerRow = appendToLedger(p, 'メール送信前');
  } catch (err) {
    // 台帳失敗はメール送信を止めないが、静かに握りつぶさずメール本文で知らせる
  }

  try {
    var body = buildMailBody(p);
    if (!ledgerRow) {
      body = '※注意: 問合せ台帳（スプレッドシート）への記録に失敗しました。台帳の存在と権限を確認してください。\n\n' + body;
    }
    GmailApp.sendEmail(DEST_EMAIL, SUBJECT, body, mailOptions);
    if (ledgerRow) {
      try { updateLedgerStatus(ledgerRow, 'メール送信済み'); } catch (err) {}
    }
  } finally {
    if (locked) lock.releaseLock();
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
// カウンタ更新はLockServiceで直列化し、並行リクエストによる上限すり抜けを防ぐ
function checkRateLimit() {
  var lock = LockService.getScriptLock();
  var locked = false;
  try { locked = lock.tryLock(3000); } catch (err) {}
  try {
    var cache = CacheService.getScriptCache();
    var now = new Date().getTime();
    var winKey = 'rate10m_' + Math.floor(now / 600000);
    var dayKey = 'rateday_' + Math.floor(now / 86400000);
    var w = Number(cache.get(winKey) || 0) + 1;
    var d = Number(cache.get(dayKey) || 0) + 1;
    cache.put(winKey, String(w), 700);
    cache.put(dayKey, String(d), 21600); // Cache上限6時間: 日次カウンタは6時間毎リセットの近似(実効50件/6h)
    return w <= 15 && d <= 50;
  } catch (err) {
    return true; // レート制限系の障害で正規の問合せを止めない（フェイルオープン）
  } finally {
    if (locked) lock.releaseLock();
  }
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
