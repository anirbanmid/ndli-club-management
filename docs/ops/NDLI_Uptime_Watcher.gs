/**
 * NDLI Uptime Watcher
 * -------------------
 * What it does:
 *   - every 5 minutes (via a trigger you set once), checks the NDLI site
 *   - if the site is DOWN  -> your Telegram bot sends YOU an alert
 *   - while it stays down  -> reminder at most once per hour (no spam)
 *   - when it comes back   -> a "back up" message
 *   - if everything is fine -> stays completely silent
 *
 * Setup (10 minutes, one time):
 *   1. Paste your BotFather token into BOT_TOKEN below (between the quotes).
 *   2. File -> Save (any name, e.g. "NDLI Uptime Watcher").
 *   3. Select function "setup" in the toolbar -> Run.
 *      (Google will ask for permission once: Review permissions ->
 *       Advanced -> Go to project -> Allow.)
 *   4. You should get a Telegram message "monitor armed" on your phone.
 *   5. Left sidebar -> Triggers (clock icon) -> "+ Add Trigger":
 *        function: checkSite
 *        event source: Time-driven
 *        type: Minutes timer
 *        interval: Every 5 minutes
 *      -> Save.
 *   Done. Nothing else to do ever.
 */

// ====== FILL THIS IN ======
var BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"; // the token BotFather gave you

// ====== Optional tweaks (safe to leave as-is) ======
var SITE_URL = "https://anirbanmid.pythonanywhere.com/";
var CHECK_KEYWORD = "";        // optional extra safety: e.g. "NDLI" ("" = off)
var REMINDER_MINUTES = 60;     // while still down, remind at most once per hour
var TIMEZONE = "Asia/Kolkata"; // only affects the timestamps in the messages

// ------------------------------------------------------------------
// Run this ONCE to find your chat and send a test message.
function setup() {
  if (BOT_TOKEN === "PASTE_YOUR_BOT_TOKEN_HERE") {
    throw new Error("First paste your BotFather token into BOT_TOKEN at the top of the code, save, and run setup() again.");
  }
  var props = PropertiesService.getScriptProperties();
  var chatId = props.getProperty("CHAT_ID");

  if (!chatId) {
    var res = UrlFetchApp.fetch("https://api.telegram.org/bot" + BOT_TOKEN + "/getUpdates", { muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) {
      throw new Error("getUpdates failed: " + res.getContentText() + "  (409 = another program is polling this bot)");
    }
    var data = JSON.parse(res.getContentText());
    if (!data.ok || !data.result || data.result.length === 0) {
      throw new Error("No messages found from you. In Telegram send /start to your bot, then run setup() again.");
    }
    var last = data.result[data.result.length - 1];
    var msg = last.message || last.edited_message || last.channel_post;
    chatId = String(msg.chat.id);
    props.setProperty("CHAT_ID", chatId);
  }

  props.setProperty("LAST_STATE", "UP");
  props.setProperty("LAST_ALERT_MS", "0");
  sendTelegram("✅ NDLI monitor armed.\nI will alert you here if " + SITE_URL + " goes down.\n(Chat id " + chatId + ")");
  Logger.log("Done. chat id = " + chatId + " — test message sent, check your phone.");
}

// ------------------------------------------------------------------
// The watchdog. Called by the trigger. Silent when all is well.
function checkSite() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty("CHAT_ID")) {
    throw new Error("No chat id stored — run setup() once first.");
  }

  var state = "UP";
  var detail = "";
  try {
    var res = UrlFetchApp.fetch(SITE_URL, { muteHttpExceptions: true, followRedirects: true });
    var code = res.getResponseCode();
    if (code !== 200) {
      state = "DOWN";
      detail = "HTTP status " + code;
    } else if (CHECK_KEYWORD && res.getContentText().indexOf(CHECK_KEYWORD) === -1) {
      state = "DOWN";
      detail = "page answered (HTTP 200) but the text '" + CHECK_KEYWORD + "' is missing";
    }
  } catch (e) {
    state = "DOWN";
    detail = "connection failed: " + e.message;
  }

  var last = props.getProperty("LAST_STATE") || "UP";
  var nowMs = new Date().getTime();

  if (state === "DOWN") {
    var lastAlert = Number(props.getProperty("LAST_ALERT_MS") || 0);
    if (last !== "DOWN" || nowMs - lastAlert > REMINDER_MINUTES * 60000) {
      sendTelegram("🚨 NDLI site is DOWN\n" + detail + "\n" + SITE_URL + "\nTime: " + nowStr());
      props.setProperty("LAST_ALERT_MS", String(nowMs));
    }
  } else if (last === "DOWN") {
    sendTelegram("✅ NDLI site is back UP.\n" + SITE_URL + "\nTime: " + nowStr());
    props.setProperty("LAST_ALERT_MS", "0");
  }

  props.setProperty("LAST_STATE", state);
}

// ------------------------------------------------------------------
function sendTelegram(text) {
  var res = UrlFetchApp.fetch("https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage", {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ chat_id: PropertiesService.getScriptProperties().getProperty("CHAT_ID"), text: text }),
    muteHttpExceptions: true
  });
  var data = JSON.parse(res.getContentText());
  if (!data.ok) throw new Error("Telegram send failed: " + res.getContentText());
}

function nowStr() {
  return Utilities.formatDate(new Date(), TIMEZONE, "yyyy-MM-dd HH:mm:ss") + " " + TIMEZONE;
}
