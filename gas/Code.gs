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
  var p = (e && e.parameter) || {};

  // ハニーポット: bot には成功を装って何もしない
  if (p._honey) {
    return jsonOut({ success: 'true' });
  }

  // 必須項目チェック（フォーム側の required と二重防御）
  if (!p['生徒氏名'] || !p['電話番号'] || !p['メールアドレス']) {
    return jsonOut({ success: 'false', message: 'required fields missing' });
  }

  var mailOptions = { name: 'Kゼミ中野校 ホームページ' };
  // 返信ボタンで保護者へ直接返信できるようにする（不正な値なら replyTo なしで送る）
  try {
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(p['メールアドレス'])) {
      mailOptions.replyTo = p['メールアドレス'];
    }
  } catch (err) {}

  GmailApp.sendEmail(DEST_EMAIL, SUBJECT, buildMailBody(p), mailOptions);

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

function jsonOut(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
