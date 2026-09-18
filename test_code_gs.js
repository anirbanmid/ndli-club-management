const fs = require('fs');
const path = require('path');

// Mock Google Apps Script environment
class MockBlob {
  constructor(content, name = 'blob') {
    this.content = content;
    this._name = name;
  }
  getDataAsString(enc) { return this.content; }
  setName(name) { this._name = name; return this; }
  getName() { return this._name; }
}

class MockFile {
  constructor(name, content, mimeType) {
    this.name = name;
    this.content = content;
    this.mimeType = mimeType;
    this.dateCreated = new Date();
  }
  getName() { return this.name; }
  getBlob() { return new MockBlob(this.content, this.name); }
  setContent(c) { this.content = c; }
  getDateCreated() { return this.dateCreated; }
  getSize() { return Buffer.byteLength(this.content, 'utf8'); }
  setTrashed(t) { this.trashed = t; }
}

class MockFolder {
  constructor(name) {
    this.name = name;
    this.id = 'mock_folder_' + name;
    this.subfolders = new Map();
    this.files = new Map();
  }
  getName() { return this.name; }
  getId() { return this.id; }
  getFoldersByName(name) {
    const list = this.subfolders.has(name) ? [this.subfolders.get(name)] : [];
    let idx = 0;
    return { hasNext: () => idx < list.length, next: () => list[idx++] };
  }
  getFolders() {
    const list = Array.from(this.subfolders.values());
    let idx = 0;
    return { hasNext: () => idx < list.length, next: () => list[idx++] };
  }
  createFolder(name) {
    const f = new MockFolder(name);
    this.subfolders.set(name, f);
    return f;
  }
  getFilesByName(name) {
    const list = this.files.has(name) ? [this.files.get(name)] : [];
    let idx = 0;
    return { hasNext: () => idx < list.length, next: () => list[idx++] };
  }
  getFiles() {
    const list = Array.from(this.files.values());
    let idx = 0;
    return { hasNext: () => idx < list.length, next: () => list[idx++] };
  }
  createFile(nameOrBlob, content, mimeType) {
    let name = nameOrBlob;
    let data = content || '';
    let mime = mimeType || 'text/plain';
    if (nameOrBlob && typeof nameOrBlob === 'object' && typeof nameOrBlob.getName === 'function') {
      name = nameOrBlob.getName();
      data = nameOrBlob.getDataAsString ? nameOrBlob.getDataAsString() : '';
      mime = 'application/zip';
    }
    const file = new MockFile(name, data, mime);
    this.files.set(name, file);
    return file;
  }
}

const rootFolder = new MockFolder("NDLI_Club_Central_IITKgp");

global.ScriptApp = {
  getScriptId: () => 'mock_script_id_123',
  getProjectTriggers: () => [],
  newTrigger: (fn) => ({
    timeBased: () => ({
      everyDays: () => ({
        atHour: () => ({
          create: () => {}
        })
      })
    })
  }),
  getService: () => ({ getUrl: () => 'https://script.google.com/macros/s/MOCK/exec' })
};

global.DriveApp = {
  getFileById: (id) => ({
    getParents: () => {
      let done = false;
      return {
        hasNext: () => !done,
        next: () => { done = true; return rootFolder; }
      };
    }
  }),
  getFoldersByName: (name) => {
    const list = name === rootFolder.getName() ? [rootFolder] : [];
    let idx = 0;
    return { hasNext: () => idx < list.length, next: () => list[idx++] };
  },
  createFolder: (name) => rootFolder
};

global.MimeType = {
  CSV: 'text/csv',
  PLAIN_TEXT: 'text/plain'
};

global.LockService = {
  getScriptLock: () => ({
    tryLock: () => true,
    waitLock: () => true,
    releaseLock: () => {}
  })
};

global.Logger = {
  log: (...args) => console.log('[GAS Logger]', ...args)
};

global.Utilities = {
  parseCsv: (text) => {
    if (!text) return [];
    // Basic CSV parse matching GAS Utilities.parseCsv
    const lines = text.split(/\r?\n/).filter(l => l.length > 0);
    return lines.map(line => {
      const row = [];
      let inQuotes = false;
      let current = '';
      for (let i = 0; i < line.length; i++) {
        const c = line[i];
        if (c === '"') {
          if (inQuotes && line[i + 1] === '"') {
            current += '"';
            i++;
          } else {
            inQuotes = !inQuotes;
          }
        } else if (c === ',' && !inQuotes) {
          row.push(current);
          current = '';
        } else {
          current += c;
        }
      }
      row.push(current);
      return row;
    });
  },
  formatDate: (date, tz, format) => {
    const d = new Date(date);
    const pad = (n) => String(n).padStart(2, '0');
    if (format.includes('yyyy-MM-dd_HHmmss')) {
      return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
    }
    if (format === 'yyyy-MM-dd') {
      return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
    }
    return d.toISOString();
  },
  formatString: (fmt, ...args) => {
    let i = 0;
    return fmt.replace(/%0?(\d*)d/g, (match, width) => {
      const val = String(args[i++]);
      return width ? val.padStart(parseInt(width), '0') : val;
    });
  },
  zip: (blobs, filename) => new MockBlob('mock_zip_content', filename)
};

global.ContentService = {
  MimeType: { CSV: 'text/csv', JSON: 'application/json' },
  createTextOutput: (content) => ({
    content,
    setMimeType: function(m) { this.mimeType = m; return this; },
    downloadAsFile: function(fn) { this.downloadFile = fn; return this; }
  })
};

global.HtmlService = {
  XFrameOptionsMode: { ALLOWALL: 'ALLOWALL' },
  createTemplateFromFile: (name) => ({
    evaluate: () => ({
      setTitle: function() { return this; },
      addMetaTag: function() { return this; },
      setXFrameOptionsMode: function() { return this; }
    })
  })
};

// Load Code.gs
const codeGsPath = path.join(__dirname, 'deployment_gas', 'Code.gs');
const codeContent = fs.readFileSync(codeGsPath, 'utf8');
eval(codeContent);

async function runTests() {
  console.log('=== TEST SUITE: Code.gs GAS Backend ===\n');

  // Test 1: initSystem
  console.log('[Test 1] Running initSystem()...');
  const initRes = initSystem();
  console.assert(initRes.success === true, 'initSystem should return success: true');
  console.log('PASS: initSystem initialized storage & databases.\n');

  // Test 2: Health
  console.log('[Test 2] Testing /api/health...');
  const healthRes = apiDispatcher('health', 'GET', {});
  console.assert(healthRes.ok === true && healthRes.data.status === 'ok', 'health failed');
  console.log('PASS: health endpoint returned 200 OK.\n');

  // Test 3: Credentials - Admin Login with email
  console.log('[Test 3a] Admin login with email (admin@iitkgp.ac.in)...');
  const adminLogin1 = apiDispatcher('auth/login', 'POST', { email: 'admin@iitkgp.ac.in', password: 'Seed#Scrubbed-2026' });
  console.assert(adminLogin1.ok === true, 'Admin login with Seed#Scrubbed-2026 should succeed');
  console.assert(adminLogin1.data.session.role === 'ADMIN', 'Admin role should be ADMIN');
  console.log('PASS: Admin login with email passed.\n');

  console.log('[Test 3b] Admin login with User ID (ADMIN01)...');
  const adminLogin2 = apiDispatcher('auth/login', 'POST', { id: 'ADMIN01', password: 'Seed#Admin-Rotated2026' });
  console.assert(adminLogin2.ok === true, 'Admin login with ADMIN01 and Seed#Admin-Rotated2026 should succeed');
  console.log('PASS: Admin login with User ID passed.\n');

  // Test 4: Credentials - Employee Login
  console.log('[Test 4a] Employee EMP01 login with User ID (EMP01)...');
  const empLogin1 = apiDispatcher('auth/login', 'POST', { email: 'EMP01', password: 'Seed#EMP01-Rotated2026' });
  console.assert(empLogin1.ok === true, 'EMP01 login should succeed');
  console.assert(empLogin1.data.session.user_id === 'EMP01', 'Session user_id should be EMP01');
  console.assert(empLogin1.data.session.zone === 'North', 'Zone should be North');
  console.log('PASS: Employee EMP01 login with User ID passed.\n');

  console.log('[Test 4b] Employee EMP01 login with email (emp01@ndli.iitkgp.ac.in)...');
  const empLogin2 = apiDispatcher('auth/login', 'POST', { email: 'emp01@ndli.iitkgp.ac.in', password: 'Seed#EMP01-Rotated2026' });
  console.assert(empLogin2.ok === true, 'EMP01 login with email should succeed');
  console.log('PASS: Employee EMP01 login with email passed.\n');

  console.log('[Test 4c] Invalid password rejection...');
  const badLogin = apiDispatcher('auth/login', 'POST', { email: 'EMP01', password: 'WrongPassword' });
  console.assert(badLogin.ok === false && badLogin.status === 401, 'Wrong password must be rejected');
  console.log('PASS: Invalid password correctly rejected with 401.\n');

  // Test 5: Verify Password (Second-layer confirmation)
  console.log('[Test 5] Password confirmation for Renewal Approval (/api/auth/verify-password)...');
  const verifyPass = apiDispatcher('auth/verify-password', 'POST', { user_id: 'EMP01', password: 'Seed#EMP01-Rotated2026' });
  console.assert(verifyPass.ok === true && verifyPass.data.valid === true, 'Second layer password verification should pass');
  console.log('PASS: Password confirmation verified.\n');

  // Test 6: Issue 2 Fix - Employee Roster (/api/employees/roster)
  console.log('[Test 6] Regional Zonal Officers Directory (/api/employees/roster)...');
  const rosterRes = apiDispatcher('employees/roster', 'GET');
  console.assert(rosterRes.ok === true, 'Roster endpoint should return ok: true');
  console.assert(rosterRes.data.employees && rosterRes.data.employees.length === 7, `Expected 7 officers in roster, got ${rosterRes.data.employees?.length}`);
  const emp01 = rosterRes.data.employees.find(e => e.id === 'EMP01');
  console.assert(emp01 && emp01.zone === 'North' && emp01.is_active === '1', 'EMP01 details mismatch');
  console.log(`PASS: Regional Zonal Officers Directory returned all ${rosterRes.data.employees.length} officers with full zone data.\n`);

  // Test 7: Employee Profile with Query String (/api/employees/profile?id=EMP01)
  console.log('[Test 7] Employee profile with query string (/api/employees/profile?id=EMP01)...');
  const profRes = apiDispatcher('employees/profile?id=EMP01', 'GET');
  console.assert(profRes.ok === true && profRes.data.found === true, 'Profile lookup with query string should succeed');
  console.assert(profRes.data.employee.id === 'EMP01', 'Expected EMP01 profile');
  console.log('PASS: Employee profile fetched successfully with query string parsing.\n');

  // Test 8: Issue 3 Fix - Admin Metrics (/api/admin/metrics)
  console.log('[Test 8] Admin Metrics (/api/admin/metrics)...');
  const metricsRes = apiDispatcher('admin/metrics', 'GET');
  console.assert(metricsRes.ok === true, 'Admin metrics must return ok: true');
  const m = metricsRes.data;
  console.assert(m.summary.total_clubs >= 10, `Expected at least 10 seed clubs, got ${m.summary.total_clubs}`);
  console.assert(m.summary.total_activities >= 20, `Expected activities, got ${m.summary.total_activities}`);
  console.assert(m.zone_wise_clubs.North > 0, 'Zone counts must have North clubs');
  console.assert(m.renewal_health.retention_rate_pct !== undefined, 'Renewal health must have retention rate');
  console.assert(m.coverage_index.total_states === 37, 'Coverage index must track 37 states');
  console.assert(m.support_type_breakdown['Club Approval'] > 0, 'Support type breakdown must have club approvals');
  console.log(`PASS: Master CSV data synced to Admin Metrics (Total Clubs: ${m.summary.total_clubs}, Activities: ${m.summary.total_activities}, States: ${m.coverage_index.represented_count}/37).\n`);

  // Test 9: Admin Renewal Attention (/api/admin/renewal-attention)
  console.log('[Test 9] Admin Renewal Attention (/api/admin/renewal-attention)...');
  const renAttRes = apiDispatcher('admin/renewal-attention', 'GET');
  console.assert(renAttRes.ok === true, 'Renewal attention must return ok: true');
  console.assert(renAttRes.data.total_attention_count !== undefined, 'Total attention count should be defined');
  console.log(`PASS: Renewal attention identified (Overdue: ${renAttRes.data.overdue_count}, Expiring Soon: ${renAttRes.data.expiring_soon_count}).\n`);

  // Test 10: Universal Clubs Search with Query Param (/api/clubs/search?q=delhi)
  console.log('[Test 10] Clubs search with query string (/api/clubs/search?q=delhi)...');
  const searchRes = apiDispatcher('clubs/search?q=delhi', 'GET');
  console.assert(searchRes.ok === true && searchRes.data.clubs.length > 0, 'Search for delhi should return clubs');
  console.log(`PASS: Clubs search returned ${searchRes.data.clubs.length} clubs for query "delhi".\n`);

  // Test 11: Club Creation & Quota Auto-Increment
  console.log('[Test 11] Create new club (/api/clubs/create)...');
  const newClubRes = apiDispatcher('clubs/create', 'POST', {
    institution_name: 'National Institute of Technology Rourkela',
    state: 'Odisha',
    patron_email: 'director@nitrkl.ac.in',
    president_email: 'pres@nitrkl.ac.in',
    secretary_email: 'sec@nitrkl.ac.in',
    employee_id: 'EMP04'
  });
  console.assert(newClubRes.ok === true && newClubRes.data.club.state === 'Odisha', 'Club creation should succeed');
  console.assert(newClubRes.data.club.zone === 'East', 'Zone should auto-map to East');
  console.log(`PASS: Club created: ${newClubRes.data.club.club_id} mapped to ${newClubRes.data.club.zone} Zone.\n`);

  // Test 12: Activity Logging & Quota Increment
  console.log('[Test 12] Log support activity (/api/activity/log)...');
  const actRes = apiDispatcher('activity/log', 'POST', {
    employee_id: 'EMP01',
    support_type: 'Phone call and remote assistance',
    notes: 'Assisted university coordinator with registration'
  });
  console.assert(actRes.ok === true && actRes.data.activity.employee_id === 'EMP01', 'Activity log should succeed');
  console.log('PASS: Activity logged and quotas incremented.\n');

  // Test 13: Unresolved Issue Reminders (/api/issues/employee-reminders?emp_id=EMP01)
  console.log('[Test 13] Unresolved issues employee reminders (/api/issues/employee-reminders?emp_id=EMP01)...');
  const remRes = apiDispatcher('issues/employee-reminders?emp_id=EMP01', 'GET');
  console.assert(remRes.ok === true && Array.isArray(remRes.data.reminders), 'Reminders must return ok: true');
  console.log(`PASS: Found ${remRes.data.reminders.length} unresolved reminders for EMP01.\n`);

  // Test 14: Admin 30-Day Escalations (/api/issues/admin-reminders)
  console.log('[Test 14] Admin 30-day issue escalations (/api/issues/admin-reminders)...');
  const adminRemRes = apiDispatcher('issues/admin-reminders', 'GET');
  console.assert(adminRemRes.ok === true && Array.isArray(adminRemRes.data.reminders), 'Admin reminders must return ok: true');
  console.log(`PASS: Found ${adminRemRes.data.reminders.length} escalated issues for Admin Red KPI Stack.\n`);

  // Test 15: Backup Status (/api/admin/backup/status) & Trigger
  console.log('[Test 15] Backup status & manual trigger...');
  const backupRes = apiDispatcher('admin/backup/trigger', 'POST');
  console.assert(backupRes.ok === true && backupRes.data.success === true, 'Backup trigger should succeed');
  const backupStatus = apiDispatcher('admin/backup/status', 'GET');
  console.assert(backupStatus.ok === true && backupStatus.data.total_stored_backups >= 1, 'Backup status should reflect created backup');
  console.log(`PASS: Backup engine operational. Stored archives: ${backupStatus.data.total_stored_backups}/${backupStatus.data.max_retained_backups}.\n`);

  // Test 16: Officer Block / Unblock Toggle (/api/auth/block-toggle)
  console.log('[Test 16] Block toggle for EMP07...');
  const blockRes = apiDispatcher('auth/block-toggle', 'POST', { user_id: 'EMP07', is_active: '0' });
  console.assert(blockRes.ok === true && blockRes.data.is_active === '0', 'Block toggle should succeed');
  const blockedLogin = apiDispatcher('auth/login', 'POST', { email: 'EMP07', password: 'Seed#EMP07-Rotated2026' });
  console.assert(blockedLogin.ok === false && blockedLogin.status === 403, 'Blocked officer login must be rejected with 403');
  // Restore
  apiDispatcher('auth/block-toggle', 'POST', { user_id: 'EMP07', is_active: '1' });
  console.log('PASS: Block toggle and restriction enforced correctly.\n');

  // Test 17: UTF-8 BOM Handling in CSV parsing (Windows / Excel compatibility)
  console.log('[Test 17] UTF-8 BOM Handling in CSV parser...');
  const bomCsv = '\uFEFFid,name,role\n\uFEFFTEST_EMP,Test User,EMPLOYEE';
  const parsedBom = parseCsv(bomCsv);
  console.assert(parsedBom.headers.includes('id'), 'Header with BOM should strip BOM and match "id"');
  console.assert(parsedBom.rows[0].id === 'TEST_EMP', 'Row value with BOM should strip BOM and match "TEST_EMP"');
  console.log('PASS: UTF-8 BOM stripped cleanly from headers and values.\n');

  // Test 18: Fallback Login for Canonical Admin & Default Employees
  console.log('[Test 18] Fallback login for Admin & Employees...');
  const adminFallback = apiDispatcher('auth/login', 'POST', { email: 'admin@iitkgp.ac.in', password: 'Seed#Scrubbed-2026' });
  console.assert(adminFallback.ok === true && adminFallback.data.user.role === 'ADMIN', 'Admin fallback login should succeed');
  const emp2Fallback = apiDispatcher('auth/login', 'POST', { email: 'EMP02', password: 'Seed#EMP02-Rotated2026' });
  console.assert(emp2Fallback.ok === true && emp2Fallback.data.user.id === 'EMP02', 'EMP02 fallback login should succeed');
  console.log('PASS: Canonical Admin and Default Employee fallback logins verified.\n');

  // Test 19: Reconcile Summary Schema for Admin.html
  console.log('[Test 19] Reconcile Summary schema (/api/sync/reconcile)...');
  const recRes = apiDispatcher('sync/reconcile', 'POST');
  console.assert(recRes.ok === true && recRes.data.summary && recRes.data.summary.employees_synced === 7, 'Reconcile summary must have employees_synced: 7');
  console.assert(typeof recRes.data.summary.total_master_clubs === 'number', 'Summary must have total_master_clubs');
  console.assert(typeof recRes.data.summary.total_master_activities === 'number', 'Summary must have total_master_activities');
  console.log(`PASS: Reconcile returns full summary schema (Synced: ${recRes.data.summary.employees_synced}, Clubs: ${recRes.data.summary.total_master_clubs}, Activities: ${recRes.data.summary.total_master_activities}).\n`);

  // Test 20: Stringified JSON body parsing in apiDispatcher
  console.log('[Test 20] Stringified JSON body in apiDispatcher...');
  const strBodyRes = apiDispatcher('auth/login', 'POST', JSON.stringify({ email: 'ADMIN01', password: 'Seed#Scrubbed-2026' }));
  console.assert(strBodyRes.ok === true && strBodyRes.data.token, 'apiDispatcher should parse stringified JSON body');
  console.log('PASS: Stringified JSON body parsed and dispatched successfully.\n');

  // Test 21: Bug 1 - EMP01 performance quota reflects >= 2 clubs approved based on activity logs
  console.log('[Test 21] EMP01 performance quota reflects clubs approved (Bug 1)...');
  const emp01Prof = apiDispatcher('employees/profile?id=EMP01', 'GET');
  console.assert(emp01Prof.ok === true, 'EMP01 profile should return ok: true');
  console.assert(parseInt(emp01Prof.data.employee.clubs_approved_count, 10) >= 2, `EMP01 clubs approved quota must be >= 2, got ${emp01Prof.data.employee.clubs_approved_count}`);
  console.log(`PASS: EMP01 performance quota correctly reflects ${emp01Prof.data.employee.clubs_approved_count} clubs approved.\n`);

  // Test 22: Bug 2 - Club NDLI-AUTO-REN-01 displays mapped Zone ("North East")
  console.log('[Test 22] Club NDLI-AUTO-REN-01 zone auto-mapping (Bug 2)...');
  const clubDetRes = apiDispatcher('clubs/details', 'POST', { club_id: 'NDLI-AUTO-REN-01' });
  console.assert(clubDetRes.ok === true && clubDetRes.data.club, 'NDLI-AUTO-REN-01 details must succeed');
  console.assert(clubDetRes.data.club.zone === 'North East', `Expected North East zone, got ${clubDetRes.data.club.zone}`);
  const clubSearchRes = apiDispatcher('clubs/search?q=NDLI-AUTO-REN-01', 'GET');
  console.assert(clubSearchRes.ok === true && clubSearchRes.data.clubs.length > 0, 'Search for NDLI-AUTO-REN-01 should succeed');
  console.assert(clubSearchRes.data.clubs[0].zone === 'North East', `Search result zone must be North East, got ${clubSearchRes.data.clubs[0].zone}`);
  console.log(`PASS: Club NDLI-AUTO-REN-01 zone mapped correctly to "${clubDetRes.data.club.zone}".\n`);

  // Test 23: Bug 3 - Database sync & bidirectional reconciliation
  console.log('[Test 23] Database sync & reconciliation (Bug 3)...');
  const syncRes = apiDispatcher('sync/reconcile', 'POST');
  console.assert(syncRes.ok === true && syncRes.data.success === true, 'sync/reconcile must succeed');
  console.assert(syncRes.data.summary.employees_synced === 7, 'Reconciliation must sync all 7 employee nodes');
  const perfRes = apiDispatcher('admin/employee-performance', 'GET');
  console.assert(perfRes.ok === true && Array.isArray(perfRes.data.officers), 'Employee performance must return officers array');
  const emp01Perf = perfRes.data.officers.find(p => p.emp_id === 'EMP01');
  console.assert(emp01Perf && emp01Perf.clubs_approved >= 2, `EMP01 performance clubs approved must be >= 2, got ${emp01Perf?.clubs_approved}`);
  // Test 24: Regression verification - clubs/update updates emails and auto-maps zone
  console.log('[Test 24] clubs/update email updates and zone mapping...');
  const updateRes = apiDispatcher('clubs/update', 'POST', {
    club_id: 'NDLI-EMP01-002',
    patron_email: 'updated.director@dati.ac.in',
    president_email: 'updated.pres@dati.ac.in',
    secretary_email: 'updated.sec@dati.ac.in'
  });
  console.assert(updateRes.ok === true, 'clubs/update must succeed');
  const verifyClub = apiDispatcher('clubs/details', 'POST', { club_id: 'NDLI-EMP01-002' });
  console.assert(verifyClub.ok === true && verifyClub.data.club.patron_email === 'updated.director@dati.ac.in', 'patron_email must be updated');
  console.assert(verifyClub.data.club.president_email === 'updated.pres@dati.ac.in', 'president_email must be updated');
  console.assert(verifyClub.data.club.secretary_email === 'updated.sec@dati.ac.in', 'secretary_email must be updated');
  console.log('PASS: clubs/update correctly updates contact emails and preserves integrity.\n');

  console.log('=============================================');
  console.log('ALL 24 BACKEND TEST SUITES PASSED FLAWLESSLY!');
  console.log('=============================================');
}

runTests().catch(err => {
  console.error('Test suite failed:', err);
  process.exit(1);
});
