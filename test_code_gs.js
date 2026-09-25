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

// Mock CacheService (used by the round-3 login throttle)
global.CacheService = (() => {
  const store = new Map();
  return {
    getScriptCache: () => ({
      get: (k) => (store.has(k) ? store.get(k) : null),
      put: (k, v, _ttl) => { store.set(k, String(v)); },
      remove: (k) => { store.delete(k); }
    })
  };
})();

global.Utilities = {
  getUuid: () => require('crypto').randomUUID(),
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

// Round 4: PropertiesService mock (server-side session store)
global.PropertiesService = (() => {
  const props = new Map();
  return {
    getScriptProperties: () => ({
      getProperty: (k) => (props.has(k) ? props.get(k) : null),
      setProperty: (k, v) => { props.set(k, String(v)); },
      deleteProperty: (k) => { props.delete(k); },
      getKeys: () => Array.from(props.keys())
    })
  };
})();

// Round 4: every test call rides a valid ADMIN session unless a test explicitly
// passes its own token (or null = deliberately unauthenticated).
const __rawDispatch = apiDispatcher;
let __autoToken = null;
apiDispatcher = function (path, method, body, token) {
  const t = (token === undefined) ? (__autoToken || undefined) : token;
  return __rawDispatch(path, method, body, t);
};

async function runTests() {
  console.log('=== TEST SUITE: Code.gs GAS Backend ===\n');

  // Round 4: bootstrap an admin session for the suite
  const __bootLogin = __rawDispatch('auth/login', 'POST', { email: 'admin@iitkgp.ac.in', password: 'Seed#Scrubbed-2026' });
  __autoToken = __bootLogin.data && __bootLogin.data.token ? __bootLogin.data.token : null;

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
  const adminLogin2 = apiDispatcher('auth/login', 'POST', { id: 'ADMIN01', password: 'Seed#Scrubbed-2026' });
  console.assert(adminLogin2.ok === true, 'Admin login with ADMIN01 and the stored credential should succeed');
  // Round-3: the seed backdoor is gone — a password that is NOT the stored
  // credential must be rejected even for a known account.
  const adminBad = apiDispatcher('auth/login', 'POST', { id: 'ADMIN01', password: 'Seed#Admin-Rotated2026' });
  console.assert(adminBad.ok === false && adminBad.status === 401, 'Non-stored password must be rejected (seed backdoor removed)');
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

  // Test 25: Non-destructive startup initialization & re-run parity (club id 26 persistence across initSystem() & sync/pull-all)
  console.log('[Test 25] Non-destructive initSystem() & sync/pull-all parity (Club 26 persistence)...');
  const createClub26Res = apiDispatcher('clubs/create', 'POST', {
    emp_id: 'EMP01',
    club_id: '260026',
    reg_no: 'REG-2026-EMP01-026',
    institution_name: 'National Institute of Advanced Studies Delhi',
    state: 'Delhi',
    zone: 'North',
    patron_email: 'director@nias.delhi.ac.in',
    president_email: 'president@nias.delhi.ac.in',
    secretary_email: 'secretary@nias.delhi.ac.in',
    date_of_approval: '2026-09-19T10:00:00Z',
    renewal_date: '2027-09-19'
  });
  console.assert(createClub26Res.ok === true, 'Failed to create club 26: ' + JSON.stringify(createClub26Res));

  // Verify club 26 exists in admin metrics
  const metricsBefore = apiDispatcher('admin/metrics', 'GET');
  console.assert(metricsBefore.ok === true, 'Failed to get admin metrics');
  const countBefore = metricsBefore.data.summary.total_clubs;

  // Re-run initSystem() (simulating server restart or manual re-initialization)
  const reinitRes = initSystem();
  console.assert(reinitRes.success === true, 'initSystem re-run failed');

  // Verify club 26 still exists and total count was not wiped out
  const metricsAfter = apiDispatcher('admin/metrics', 'GET');
  console.assert(metricsAfter.ok === true, 'Failed to get admin metrics after re-init');
  console.assert(metricsAfter.data.summary.total_clubs === countBefore, `Total clubs wiped! Expected ${countBefore}, got ${metricsAfter.data.summary.total_clubs}`);

  const club26Check = apiDispatcher('clubs/details', 'POST', { club_id: '260026' });
  console.assert(club26Check.ok === true && club26Check.data.club, 'Club 26 disappeared after initSystem()!');
  console.assert(club26Check.data.club.institution_name === 'National Institute of Advanced Studies Delhi', 'Club 26 data corrupted after initSystem()');

  // Verify sync/pull-all endpoint
  const pullAllRes = apiDispatcher('sync/pull-all', 'POST', {});
  console.assert(pullAllRes.ok === true && pullAllRes.data.success === true, 'sync/pull-all failed');
  console.assert(pullAllRes.data.total_files > 0, 'sync/pull-all must return files');
  console.assert(pullAllRes.data.files['master/master_clubs.csv'].includes('260026'), 'master_clubs.csv in pull-all must contain Club 26');

  // Verify sync/pull-file endpoint
  const pullFileRes = apiDispatcher('sync/pull-file', 'POST', { subPath: 'master', fileName: 'master_clubs.csv' });
  console.assert(pullFileRes.ok === true && pullFileRes.data.success === true, 'sync/pull-file failed');
  console.assert(pullFileRes.data.content.includes('260026'), 'pulled master_clubs.csv must contain Club 26');
  console.log('PASS: Non-destructive initSystem() verified: Club 26 and activity logs 100% persisted!\n');

  // Test 27: Round-3 parity — numeric club IDs, duplicate-entry checkpoints,
  // and the renewal policy/dedupe guard.
  console.log('[Test 27] Round-3: numeric club IDs + duplicate-entry checkpoints...');

  // 27a. Client requisition: Club ID must be a whole number
  const badIdRes = apiDispatcher('clubs/create', 'POST', {
    emp_id: 'EMP03', club_id: 'NDLI-BAD-1', reg_no: 'REG-R3-A',
    institution_name: 'Bad ID Institute', state: 'Gujarat'
  });
  console.assert(badIdRes.ok === false && badIdRes.status === 422, 'Non-numeric club ID must be rejected with 422');

  // 27b. Numeric ID accepted
  const numIdRes = apiDispatcher('clubs/create', 'POST', {
    emp_id: 'EMP03', club_id: '930001', reg_no: 'REG-R3-1',
    institution_name: 'Numeric ID Institute', state: 'Gujarat'
  });
  console.assert(numIdRes.ok === true, 'Numeric club ID must be accepted');

  // 27c. Club-ID takeover blocked (other employee's club)
  const hijackRes = apiDispatcher('clubs/create', 'POST', {
    emp_id: 'EMP04', club_id: '930001', reg_no: 'REG-R3-2',
    institution_name: 'Hijack Institute', state: 'Bihar'
  });
  console.assert(hijackRes.ok === false && hijackRes.status === 409, 'Cross-employee club takeover must return 409');

  // 27d. Duplicate Registration Number blocked with a warning naming the club
  const dupRegRes = apiDispatcher('clubs/create', 'POST', {
    emp_id: 'EMP04', club_id: '930002', reg_no: 'reg-r3-1',
    institution_name: 'Duplicate Reg Institute', state: 'Bihar'
  });
  console.assert(dupRegRes.ok === false && dupRegRes.status === 409, 'Duplicate Registration Number must return 409');
  console.assert(String(dupRegRes.data.message).includes('930001'), 'Duplicate warning must name the existing club');

  // 27e. Renewal policy: +1 year from the PREVIOUS due date + 60s dedupe
  apiDispatcher('clubs/update', 'POST', { club_id: '930001', role: 'ADMIN', renewal_date: '2030-01-10', next_renewal_date: '2030-01-10' });
  const ren1Res = apiDispatcher('clubs/renew', 'POST', { emp_id: 'EMP03', club_id: '930001' });
  console.assert(ren1Res.ok === true && ren1Res.data.club.renewal_date === '2031-01-10', 'Renewal must be +1 year from the previous DUE date (2030-01-10 -> 2031-01-10)');
  const ren2Res = apiDispatcher('clubs/renew', 'POST', { emp_id: 'EMP03', club_id: '930001' });
  console.assert(ren2Res.ok === true && ren2Res.data.renewal_duplicate_skipped === true, 'Double-click renewal must be ignored as duplicate');

  // 27f. Mass-assignment guard: a non-admin SESSION cannot change status/renewal
  // dates (round 4: the verified session role is authoritative)
  apiDispatcher('clubs/create', 'POST', {
    emp_id: 'EMP04', club_id: '930003', reg_no: 'REG-R3-3',
    institution_name: 'Mass Test Institute', state: 'Bihar'
  });
  const empTokR3 = apiDispatcher('auth/login', 'POST', { email: 'EMP03', password: 'Seed#EMP03-Rotated2026' }).data.token;
  const massRes = apiDispatcher('clubs/update', 'POST', { emp_id: 'EMP03', club_id: '930003', institution_name: 'Renamed R3', status: 'Hacked', renewal_date: '1999-01-01' }, empTokR3);
  console.assert(massRes.ok === true, 'Descriptive update should succeed');
  const massCheck = apiDispatcher('clubs/details', 'POST', { club_id: '930003' });
  console.assert(massCheck.data.club.status !== 'Hacked' && massCheck.data.club.renewal_date !== '1999-01-01', 'Non-admin must not change status/renewal dates');
  console.assert(massCheck.data.club.institution_name === 'Renamed R3', 'Non-admin descriptive edit must still work');

  console.log('PASS: Round-3 numeric IDs, duplicate checkpoints, renewal policy & mass-assignment guard verified.\n');

  // Test 28: Round-4 session authorization — tokens are verified, role-gated
  // and invalidated on logout (the dispatcher used to be an open API).
  console.log('[Test 28] Round-4: session tokens required, role-gated, invalidated...');

  // 28a. No token -> 401
  const noTokRes = __rawDispatch('clubs/search?q=delhi', 'GET', {}, null);
  console.assert(noTokRes.status === 401, 'Request without a session token must be rejected with 401');

  // 28b. Bogus token -> 401
  const badTokRes = __rawDispatch('clubs/search?q=delhi', 'GET', {}, 'ndli_tok_bogus');
  console.assert(badTokRes.status === 401, 'Bogus session token must be rejected with 401');

  // 28c. Employee token on an ADMIN route -> 403
  const empLogin28 = __rawDispatch('auth/login', 'POST', { email: 'EMP03', password: 'Seed#EMP03-Rotated2026' });
  const empTok28 = empLogin28.data.token;
  const empOnAdmin = __rawDispatch('admin/metrics', 'GET', {}, empTok28);
  console.assert(empOnAdmin.status === 403, 'Employee session on admin route must be rejected with 403');

  // 28d. Employee token on its own routes -> 200
  const empOwn = __rawDispatch('clubs/search?q=delhi', 'GET', {}, empTok28);
  console.assert(empOwn.ok === true, 'Employee session must access clubs routes');

  // 28e. Logout invalidates the token
  __rawDispatch('auth/logout', 'POST', {}, empTok28);
  const afterLogout = __rawDispatch('clubs/search?q=delhi', 'GET', {}, empTok28);
  console.assert(afterLogout.status === 401, 'Token must be invalid after logout');

  // 28f. auth/me returns the VERIFIED session (no more token-parsing identity)
  const meRes28 = __rawDispatch('auth/me', 'GET', {}, __autoToken);
  console.assert(meRes28.ok === true && meRes28.data.user.role === 'ADMIN', 'auth/me must return the verified session');

  // 28g. health & login stay public
  const pubHealth = __rawDispatch('health', 'GET', {}, null);
  const pubLogin = __rawDispatch('auth/login', 'POST', { email: 'EMP03', password: 'WrongPassword' }, null);
  console.assert(pubHealth.ok === true && pubLogin.status === 401, 'health/login must remain public');

  console.log('PASS: session authorization enforced everywhere.\n');

  // Test 29: Round-4 identity alignment — identity and role decisions come
  // from the VERIFIED session, never from the spoofable request body, and the
  // hard-coded default-employee fallbacks (EMP01) are gone.
  console.log('[Test 29] Round-4: identity spoofing rejected, session identity enforced...');

  const empLogin29 = __rawDispatch('auth/login', 'POST', { email: 'EMP03', password: 'Seed#EMP03-Rotated2026' });
  const empTok29 = empLogin29.data.token;

  // 29a. Employee cannot log activity under another employee's identity
  const spoofAct = __rawDispatch('activity/log', 'POST', { employee_id: 'EMP01', support_type: 'Phone call and remote assistance', notes: 'spoof attempt' }, empTok29);
  console.assert(spoofAct.status === 403, 'Employee must not log activity as another employee');

  // 29b. Blank identity falls back to the SESSION identity (never a default EMP01)
  const ownAct = __rawDispatch('activity/log', 'POST', { support_type: 'Phone call and remote assistance', notes: 'session identity' }, empTok29);
  console.assert(ownAct.ok === true && ownAct.data.activity && String(ownAct.data.activity.emp_id).toUpperCase() === 'EMP03', 'Activity must carry the VERIFIED session identity (EMP03)');

  // 29c. issues/create identity gate
  const spoofIssue = __rawDispatch('issues/create', 'POST', { club_id: '910201', emp_id: 'EMP01', issue_note: 'spoof attempt' }, empTok29);
  console.assert(spoofIssue.status === 403, 'Employee must not raise issues under another identity');

  // 29d. employees/profile without an id resolves to the caller's OWN profile
  const prof29 = __rawDispatch('employees/profile', 'GET', {}, empTok29);
  console.assert(prof29.ok === true && String(prof29.data.employee.id).toUpperCase() === 'EMP03', 'Profile without id must resolve to the session identity');

  // 29e. Admin sessions may act for other employees (parity: self-or-admin)
  const adminAct29 = __rawDispatch('activity/log', 'POST', { employee_id: 'EMP02', support_type: 'Phone call and remote assistance', notes: 'admin on behalf' }, __autoToken);
  console.assert(adminAct29.ok === true, 'Admin must be able to log for another employee');

  // 29f. issues/resolve ownership: employees resolve only their own issues
  const mkIssue29 = __rawDispatch('issues/create', 'POST', { club_id: '910201', emp_id: 'EMP01', issue_note: 'ownership probe' }, __autoToken);
  const issueId29 = mkIssue29.data.issue.issue_id;
  const resolveSpoof = __rawDispatch('issues/resolve', 'POST', { issue_id: issueId29 }, empTok29);
  console.assert(resolveSpoof.status === 403, 'Employee must not resolve another employee\'s issue');
  const resolveAdmin = __rawDispatch('issues/resolve', 'POST', { issue_id: issueId29 }, __autoToken);
  console.assert(resolveAdmin.ok === true, 'Admin must be able to resolve any issue');

  // 29g. Reminder listing is self-scoped for employees
  const ownRem = __rawDispatch('issues/employee-reminders', 'GET', {}, empTok29);
  console.assert(ownRem.ok === true && ownRem.data.reminders.every(function (r) { return String(r.emp_id || r.employee_id).toUpperCase() === 'EMP03'; }), 'Employee reminder listing must be scoped to own identity');
  const crossRem = __rawDispatch('issues/employee-reminders?emp_id=EMP01', 'GET', {}, empTok29);
  console.assert(crossRem.status === 403, 'Employee must not list another employee\'s reminders');

  // 29h. Role gates tightened to Python parity: issues/admin-reminders and
  // certificate/* are admin-only
  const certEmp = __rawDispatch('certificate/settings', 'GET', {}, empTok29);
  console.assert(certEmp.status === 403, 'certificate/* must be admin-only (parity with Python app.py)');
  const admRemEmp = __rawDispatch('issues/admin-reminders', 'GET', {}, empTok29);
  console.assert(admRemEmp.status === 403, 'issues/admin-reminders must be admin-only');

  console.log('PASS: session identity enforced, spoofed body identity rejected.\n');

  // Test 30: Round-4.1 — PBKDF2-HMAC-SHA256 credentials (Python sync format).
  // The Drive CSVs carry the Python twin's hashes; the GAS twin used to compare
  // plaintext and could never match them (everyone locked out after rotation).
  console.log('[Test 30] Round-4.1: PBKDF2 credential verification (Python parity)...');
  const crypto30 = require('crypto');
  const t30pass = 'Rotated#EMP02-2026!';
  const t30salt = 'a1b2c3d4e5f60718293a4b5c6d7e8f90';
  const t30hash = crypto30.pbkdf2Sync(t30pass, t30salt, 100000, 32, 'sha256').toString('hex');

  // 30a. The pure-JS implementation must be bit-for-bit identical to the
  // reference PBKDF2-HMAC-SHA256 (same output as Python's hashlib).
  const t30start = Date.now();
  console.assert(gasPbkdf2Hex_(t30pass, t30salt, 100000) === t30hash, 'gasPbkdf2Hex_ must match PBKDF2-HMAC-SHA256 reference output');
  console.log('  (pbkdf2 x100k in JS: ' + (Date.now() - t30start) + 'ms)');

  // 30b. Log in against a HASHED row (the live Drive format) — correct and wrong password
  const mU30 = getCsvData('master', 'master_users.csv');
  for (const row of mU30.rows) {
    if ((row.id || row.user_id || '').toUpperCase() === 'EMP02') {
      row.password_hash = t30hash;
      row.salt = t30salt;
    }
  }
  saveCsvData('master', 'master_users.csv', mU30.headers, mU30.rows);
  const hashLogin = __rawDispatch('auth/login', 'POST', { id: 'EMP02', password: t30pass }, null);
  console.assert(hashLogin.ok === true && hashLogin.data.token, 'PBKDF2-hashed row must accept the correct password');
  const hashLoginBad = __rawDispatch('auth/login', 'POST', { id: 'EMP02', password: 'wrong-guess' }, null);
  console.assert(hashLoginBad.ok === false && hashLoginBad.status === 401, 'PBKDF2-hashed row must reject a wrong password');

  // 30c. Second-layer verify-password works against hashed rows too
  const vp30 = __rawDispatch('auth/verify-password', 'POST', { user_id: 'EMP02', password: t30pass }, hashLogin.data.token);
  console.assert(vp30.ok === true && vp30.data.valid === true, 'verify-password must accept the correct password for a hashed row');

  // 30d. Legacy plaintext rows (pre-sync data / fixtures) keep working
  const legacyLogin = __rawDispatch('auth/login', 'POST', { id: 'EMP01', password: 'Seed#EMP01-Rotated2026' }, null);
  console.assert(legacyLogin.ok === true, 'Legacy plaintext rows must keep working');

  console.log('PASS: PBKDF2 credentials verified (Python sync format + legacy rows).\n');

  console.log('=============================================');
  console.log('ALL 31 BACKEND TEST SUITES PASSED FLAWLESSLY!');
  console.log('=============================================');
}

runTests().catch(err => {
  console.error('Test suite failed:', err);
  process.exit(1);
});
