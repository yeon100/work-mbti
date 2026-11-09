// 구글 시트 → 확장 프로그램 → Apps Script에 붙여 넣고 웹 앱으로 배포합니다.

const SHEET_NAME = "응답";
const HEADERS = ["제출시각", "팀", "이름", "캐릭터", "일 처리", "협업", "에너지", "응답", "runId"];

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const data = JSON.parse(e.postData.contents);
    const sheet = getSheet_();
    const runId = clean_(data.runId);

    if (runId && sheet.getLastRow() > 1) {
      const found = sheet
        .getRange(2, HEADERS.length, sheet.getLastRow() - 1, 1)
        .createTextFinder(runId)
        .matchEntireCell(true)
        .findNext();
      if (found) return json_({ ok: true, duplicate: true });
    }

    sheet.appendRow([
      new Date(),
      clean_(data.team),
      clean_(data.name),
      clean_(data.character),
      clean_(data.work),
      clean_(data.collab),
      clean_(data.energy),
      clean_((data.answers || []).join(" "), 200),
      runId,
    ]);
    return json_({ ok: true });
  } finally {
    lock.releaseLock();
  }
}

function doGet() {
  return json_({ ok: true, message: "work-mbti 결과 수집 주소가 동작 중이에요" });
}

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(SHEET_NAME);
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

// =, +, -, @로 시작하는 값은 시트가 수식으로 실행하므로 앞에 '를 붙인다.
function clean_(value, max) {
  const s = String(value == null ? "" : value).trim().slice(0, max || 50);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
