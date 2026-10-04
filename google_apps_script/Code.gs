/**
 * NDLI Club Management and Employee Activity Tracking System
 * Google Apps Script (GAS) Web App & Drive Integration Module
 *
 * This script runs natively in Google Drive / Google Apps Script.
 * It manages CSV databases stored directly within a single Google Drive folder.
 */

// Configuration: Replace with your specific Google Drive Folder ID
var CONFIG = {
  DRIVE_FOLDER_ID: "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE",
  ADMIN_EMAIL: "admin@iitkgp.ac.in",
  ZONE_MAPPING: {
    "North": ["Jammu & Kashmir", "Ladakh", "Uttarakhand", "Himachal Pradesh", "Chandigarh", "Punjab", "Haryana", "Delhi", "Uttar Pradesh"],
    "Central": ["Madhya Pradesh", "Chhattisgarh"],
    "West": ["Rajasthan", "Gujarat", "Maharashtra", "Goa", "Daman and Diu", "Dadar & Nagar Haveli"],
    "East": ["Bihar", "Jharkhand", "West Bengal", "Odisha"],
    "North East": ["Sikkim", "Assam", "Arunachal Pradesh", "Meghalaya", "Manipur", "Tripura", "Nagaland", "Mizoram"],
    "South": ["Andhra Pradesh", "Telangana", "Karnataka", "Tamil Nadu", "Puducherry", "Kerala", "Andaman & Nicobar Island", "Lakshadweep"]
  }
};

/**
 * Serves the HTML frontend when accessed as a Google Apps Script Web App.
 */
function doGet(e) {
  var template = HtmlService.createTemplateFromFile("Index");
  return template.evaluate()
    .setTitle("NDLI Club Management System - IIT Kharagpur")
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag("viewport", "width=device-width, initial-scale=1");
}

/**
 * Helper to get or create a CSV file inside the designated Drive folder.
 */
function getOrCreateCsvFile(folder, filename, headerArray) {
  var files = folder.getFilesByName(filename);
  if (files.hasNext()) {
    return files.next();
  }
  var csvContent = headerArray.join(",") + "\n";
  return folder.createFile(filename, csvContent, MimeType.PLAIN_TEXT);
}

/**
 * Reads CSV file from Drive folder and returns array of objects.
 */
function readCsvData(filename) {
  var folder = DriveApp.getFolderById(CONFIG.DRIVE_FOLDER_ID);
  var files = folder.getFilesByName(filename);
  if (!files.hasNext()) return [];
  
  var file = files.next();
  var content = file.getBlob().getDataAsString("utf-8");
  var csvRows = Utilities.parseCsv(content);
  if (csvRows.length < 2) return [];

  var headers = csvRows[0];
  var results = [];
  for (var i = 1; i < csvRows.length; i++) {
    var rowObj = {};
    for (var j = 0; j < headers.length; j++) {
      rowObj[headers[j]] = csvRows[i][j] || "";
    }
    results.push(rowObj);
  }
  return results;
}

/**
 * Appends a row to a CSV file in Google Drive.
 */
function appendCsvRow(filename, rowObject, headers) {
  var folder = DriveApp.getFolderById(CONFIG.DRIVE_FOLDER_ID);
  var file = getOrCreateCsvFile(folder, filename, headers);
  var existingContent = file.getBlob().getDataAsString("utf-8");
  
  var rowValues = headers.map(function(h) {
    var val = (rowObject[h] || "").toString().replace(/"/g, '""');
    return '"' + val + '"';
  });
  
  var newContent = existingContent + (existingContent.endsWith("\n") ? "" : "\n") + rowValues.join(",") + "\n";
  file.setContent(newContent);
  return true;
}

/**
 * Maps State to Zone based on predefined Indian regional classification.
 */
function getZoneForState(stateName) {
  if (!stateName) return "";
  var clean = stateName.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9 ]/g, "").trim();
  
  for (var zone in CONFIG.ZONE_MAPPING) {
    var states = CONFIG.ZONE_MAPPING[zone];
    for (var i = 0; i < states.length; i++) {
      var sClean = states[i].toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9 ]/g, "").trim();
      if (sClean === clean) {
        return zone;
      }
    }
  }
  return "";
}

/**
 * API handler for Employee Club Approval & Sync to Master.
 */
function apiApproveClub(empId, clubData) {
  var headers = [
    "club_id", "reg_no", "institution_name", "state", "zone",
    "patron_email", "president_email", "secretary_email",
    "submission_timestamp", "renewal_date", "status", "approved_by_emp_id", "updated_at"
  ];
  
  clubData.zone = getZoneForState(clubData.state);
  clubData.submission_timestamp = new Date().toISOString();
  clubData.updated_at = clubData.submission_timestamp;
  clubData.status = "Approved";
  clubData.approved_by_emp_id = empId;

  // 1. Write to Employee CSV
  var empFilename = "clubs_" + empId.toLowerCase() + ".csv";
  appendCsvRow(empFilename, clubData, headers);

  // 2. Write to Master CSV
  appendCsvRow("master_clubs.csv", clubData, headers);

  return { success: true, club: clubData };
}
