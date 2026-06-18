// SFERO Meta Ads — Google Sheets Webhook
// Деплой: Розширення → Apps Script → вставити код → Розгорнути → Веб-застосунок
// Доступ: Усі (анонімні)

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // Daily sheet
    var ws = ss.getSheetByName("Daily") || ss.insertSheet("Daily");
    if (ws.getLastRow() === 0) {
      ws.appendRow([
        "Дата", "Витрати $", "Покази", "Кліки", "CTR %",
        "CPC $", "Охоплення", "Frequency", "LPV", "Конверсія %", "Ліди", "CPL $"
      ]);
      // Форматування заголовків
      ws.getRange(1, 1, 1, 12).setBackground("#1a73e8").setFontColor("white").setFontWeight("bold");
      ws.setFrozenRows(1);
    }

    ws.appendRow([
      data.date, data.spend, data.impressions, data.clicks,
      data.ctr,  data.cpc,   data.reach,       data.freq,
      data.lpv,  data.conv,  data.leads,       data.cpl
    ]);

    // Автоширина колонок
    ws.autoResizeColumns(1, 12);

    return ContentService
      .createTextOutput(JSON.stringify({status: "ok"}))
      .setMimeType(ContentService.MimeType.JSON);

  } catch(err) {
    return ContentService
      .createTextOutput(JSON.stringify({status: "error", message: err.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput("SFERO webhook is running ✅");
}
