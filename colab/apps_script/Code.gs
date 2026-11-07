/**
 * Style Vote connector (Google Apps Script).
 *
 * Links the Google Sheet to the two web pages:
 *   - the customer voting page reads active designs + trend polls and POSTs votes;
 *   - the business dashboard reads the notebook's results with an access key,
 *     plus live vote counts (so new votes show before the notebook is rerun).
 *
 * Setup: Extensions → Apps Script in the Google Sheet, paste this file, run `setup`
 * once (it creates the `votes` tab and prints your business access key in the log),
 * then Deploy → New deployment → Web app (Execute as: Me · Who has access: Anyone).
 */

const VOTE_HEADERS = ['timestamp', 'voter_id', 'type', 'item_id', 'rating', 'colour',
                      'price_answer', 'answer', 'age_range', 'source'];
const BUSINESS_TABS = ['run_info', 'briefs', 'buy_plan', 'trends', 'colours', 'vote_summary',
                       'model_report', 'designs', 'trend_polls'];
const AGE_RANGES = ['', '16-24', '25-34', '35-44', '45-54', '55+'];
const MAX_VOTES_PER_HOUR = 60;

function setup() {
  votesSheet_();
  const props = PropertiesService.getScriptProperties();
  let key = props.getProperty('BUSINESS_KEY');
  if (!key) {
    key = Utilities.getUuid().slice(0, 8);
    props.setProperty('BUSINESS_KEY', key);
  }
  Logger.log('Business dashboard access key: ' + key);
}

function doGet(e) {
  const p = (e && e.parameter) || {};
  const action = p.action || 'public';
  if (action === 'public') {
    return json_({
      designs: readTab_('designs').filter(isActive_).map(publicDesign_),
      trend_polls: readTab_('trend_polls'),
    });
  }
  if (action === 'business') {
    const key = PropertiesService.getScriptProperties().getProperty('BUSINESS_KEY');
    if (!key || p.key !== key) return json_({ error: 'Wrong or missing access key.' });
    const out = {};
    BUSINESS_TABS.forEach(function (t) { out[t] = readTab_(t); });
    out.live_votes = liveVoteStats_(readTab_('votes'));
    return json_(out);
  }
  return json_({ error: 'Unknown action.' });
}

function doPost(e) {
  let d;
  try {
    d = JSON.parse(e.postData.contents);
  } catch (err) {
    return json_({ ok: false, error: 'Bad request.' });
  }
  const problem = validate_(d);
  if (problem) return json_({ ok: false, error: problem });

  const cache = CacheService.getScriptCache();
  const rateKey = 'rate_' + d.voter_id;
  const count = Number(cache.get(rateKey) || 0);
  if (count >= MAX_VOTES_PER_HOUR) return json_({ ok: false, error: 'Too many votes — try again later.' });
  cache.put(rateKey, String(count + 1), 3600);

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    votesSheet_().appendRow([
      Utilities.formatDate(new Date(), 'UTC', 'yyyy-MM-dd HH:mm:ss'),
      d.voter_id, d.type, d.item_id,
      d.type === 'design' ? Number(d.rating) : '',
      d.colour || '', d.price_answer || '', d.answer || '', d.age_range || '',
      String(d.source || '').slice(0, 30),
    ]);
  } finally {
    lock.releaseLock();
  }
  return json_({ ok: true });
}

function validate_(d) {
  if (!d || typeof d !== 'object') return 'Bad request.';
  if (!/^[A-Za-z0-9-]{8,40}$/.test(String(d.voter_id || ''))) return 'Missing voter id.';
  if (AGE_RANGES.indexOf(String(d.age_range || '')) < 0) return 'Unknown age range.';
  if (d.type === 'design') {
    const design = readTab_('designs').filter(isActive_).find(function (r) { return r.design_id === d.item_id; });
    if (!design) return 'Unknown design.';
    const rating = Number(d.rating);
    if (!(rating >= 1 && rating <= 5 && Math.round(rating) === rating)) return 'Rating must be 1–5.';
    const colours = String(design.colours || '').split(',').map(function (c) { return c.trim(); });
    if (d.colour && colours.indexOf(d.colour) < 0) return 'Unknown colour.';
    if (['', 'yes', 'maybe', 'no'].indexOf(String(d.price_answer || '')) < 0) return 'Unknown price answer.';
    return null;
  }
  if (d.type === 'trend') {
    const poll = readTab_('trend_polls').find(function (r) { return r.trend_id === d.item_id; });
    if (!poll) return 'Unknown trend.';
    if (['hot', 'not'].indexOf(d.answer) < 0) return 'Answer must be hot or not.';
    return null;
  }
  return 'Unknown vote type.';
}

/** Live per-design and per-trend counts, one vote per voter per item (their latest). */
function liveVoteStats_(votes) {
  const latest = {};
  votes.forEach(function (v) { latest[v.voter_id + '|' + v.item_id] = v; });
  const stats = {};
  Object.keys(latest).forEach(function (k) {
    const v = latest[k];
    const s = stats[v.item_id] || (stats[v.item_id] = {
      item_id: v.item_id, type: v.type, n_votes: 0, rating_sum: 0, approvals: 0,
      price_yes: 0, hot: 0, colours: {}, last_vote: '',
    });
    s.n_votes += 1;
    if (v.type === 'design') {
      const r = Number(v.rating) || 0;
      s.rating_sum += r;
      if (r >= 4) s.approvals += 1;
      if (v.price_answer === 'yes') s.price_yes += 1;
      if (v.colour) s.colours[v.colour] = (s.colours[v.colour] || 0) + 1;
    } else if (v.answer === 'hot') {
      s.hot += 1;
    }
    if (String(v.timestamp) > s.last_vote) s.last_vote = String(v.timestamp);
  });
  return Object.keys(stats).map(function (id) {
    const s = stats[id];
    const top = Object.keys(s.colours).sort(function (a, b) { return s.colours[b] - s.colours[a]; })[0] || '';
    return {
      item_id: id, type: s.type, n_votes: s.n_votes,
      avg_rating: s.type === 'design' ? round_(s.rating_sum / s.n_votes) : '',
      approval: s.type === 'design' ? round_(s.approvals / s.n_votes) : '',
      would_buy: s.type === 'design' ? round_(s.price_yes / s.n_votes) : '',
      top_colour: top, hot_share: s.type === 'trend' ? round_(s.hot / s.n_votes) : '',
      last_vote: s.last_vote,
    };
  });
}

function publicDesign_(r) {
  return {
    design_id: r.design_id, garment: r.garment, name: r.name, description: r.description,
    colours: r.colours, colour_hex: r.colour_hex, price_eur: r.price_eur, multiway: r.multiway,
    sustainable: r.sustainable, image_url: r.image_url, image_urls: r.image_urls || '',
  };
}

function readTab_(name) {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sh || sh.getLastRow() < 2) return [];
  const values = sh.getDataRange().getValues();
  const headers = values.shift().map(String);
  return values.filter(function (row) { return row.some(function (c) { return c !== ''; }); })
    .map(function (row) {
      const o = {};
      headers.forEach(function (h, i) {
        const v = row[i];
        o[h] = v instanceof Date ? Utilities.formatDate(v, 'UTC', 'yyyy-MM-dd HH:mm:ss') : v;
      });
      return o;
    });
}

function votesSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName('votes');
  if (!sh) {
    sh = ss.insertSheet('votes');
    sh.appendRow(VOTE_HEADERS);
    sh.setFrozenRows(1);
  }
  return sh;
}

function isActive_(r) {
  return String(r.active).toUpperCase() === 'TRUE';
}

function round_(x) {
  return Math.round(x * 1000) / 1000;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
