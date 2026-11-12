// 구글 시트 → 확장 프로그램 → Apps Script에 붙여 넣고 웹 앱으로 배포합니다.

const SHEET_NAME = "응답";
const HEADERS = ["제출시각", "팀", "이름", "캐릭터", "일 처리", "협업", "에너지", "응답", "runId", "성향 지수"];

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const data = JSON.parse(e.postData.contents);
    const sheet = getSheet_();
    const cols = headerMap_(sheet);
    const runId = clean_(data.runId);

    if (runId && cols.runId && sheet.getLastRow() > 1) {
      const found = sheet
        .getRange(2, cols.runId, sheet.getLastRow() - 1, 1)
        .createTextFinder(runId)
        .matchEntireCell(true)
        .findNext();
      if (found) return json_({ ok: true, duplicate: true });
    }

    const values = {
      제출시각: new Date(),
      팀: clean_(data.team),
      이름: clean_(data.name),
      캐릭터: clean_(data.character),
      "일 처리": clean_(data.work),
      협업: clean_(data.collab),
      에너지: clean_(data.energy),
      응답: clean_((data.answers || []).join(" "), 800),
      runId: runId,
      "성향 지수": clean_(data.index, 80),
    };
    const width = sheet.getLastColumn();
    const row = new Array(width).fill("");
    Object.keys(values).forEach((key) => {
      if (cols[key]) row[cols[key] - 1] = values[key];
    });
    sheet.appendRow(row);
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
    return sheet;
  }
  const width = Math.max(sheet.getLastColumn(), 1);
  const row = sheet.getRange(1, 1, 1, width).getValues()[0].map((v) => String(v).trim());
  HEADERS.forEach((header) => {
    if (row.indexOf(header) === -1) {
      sheet.getRange(1, sheet.getLastColumn() + 1).setValue(header);
      row.push(header);
    }
  });
  return sheet;
}

function headerMap_(sheet) {
  const width = Math.max(sheet.getLastColumn(), 1);
  const row = sheet.getRange(1, 1, 1, width).getValues()[0].map((v) => String(v).trim());
  const map = {};
  row.forEach((header, i) => {
    if (header) map[header] = i + 1;
  });
  return map;
}

// =, +, -, @로 시작하는 값은 시트가 수식으로 실행하므로 앞에 '를 붙인다.
function clean_(value, max) {
  const s = String(value == null ? "" : value).trim().slice(0, max || 50);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
