/* mymusic — supervision
   Polls /api/dashboard and repaints. No framework, no build step. */

'use strict';

/* Point this at your tunnel hostname. Falls back to the NAS on the LAN. */
var API_BASE = 'https://dashboard.mymusic-nj.com';
var API_FALLBACK = 'http://100.69.220.88:5053';

var REFRESH_MS = 15000;
var STORAGE_KEY = 'mymusic.dashboard.token';

var base = API_BASE;
var token = '';
var timer = null;

/* ------------------------------------------------------------------ */
/* storage (private browsing can throw on access)                      */
/* ------------------------------------------------------------------ */

function readToken() {
  try { return window.localStorage.getItem(STORAGE_KEY) || ''; }
  catch (e) { return ''; }
}

function writeToken(value) {
  try { window.localStorage.setItem(STORAGE_KEY, value); }
  catch (e) { /* session-only is fine */ }
}

function clearToken() {
  try { window.localStorage.removeItem(STORAGE_KEY); }
  catch (e) { /* no-op */ }
}

/* ------------------------------------------------------------------ */
/* formatting                                                          */
/* ------------------------------------------------------------------ */

function bytes(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  var units = ['o', 'ko', 'Mo', 'Go', 'To'];
  var i = 0;
  var v = Number(n);
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return (v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)) + ' ' + units[i];
}

function num(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return Number(n).toLocaleString('fr-FR');
}

function duration(seconds) {
  if (!seconds) return '—';
  var h = Math.floor(seconds / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  if (h >= 24) {
    var d = Math.floor(h / 24);
    return d + ' j ' + (h % 24) + ' h';
  }
  if (h) return h + ' h ' + String(m).padStart(2, '0');
  return m + ' min';
}

function shortDate(iso) {
  if (!iso) return '—';
  var d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: '2-digit' });
}

function clockTime(iso) {
  var d = iso ? new Date(iso) : new Date();
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function level(percent) {
  if (percent >= 90) return 'bad';
  if (percent >= 75) return 'warn';
  return 'ok';
}

function el(id) { return document.getElementById(id); }

function text(node, value) { node.textContent = value; }

/* ------------------------------------------------------------------ */
/* gate                                                                */
/* ------------------------------------------------------------------ */

function showGate(failed) {
  el('app').hidden = true;
  el('gate').hidden = false;
  el('gateError').hidden = !failed;
  el('tokenInput').focus();
  if (timer) { clearInterval(timer); timer = null; }
}

function showApp() {
  el('gate').hidden = true;
  el('app').hidden = false;
}

function submitToken() {
  var value = el('tokenInput').value.trim();
  if (!value) return;
  token = value;
  writeToken(value);
  el('tokenInput').value = '';
  start();
}

/* ------------------------------------------------------------------ */
/* fetch                                                               */
/* ------------------------------------------------------------------ */

function request(host) {
  return fetch(host + '/api/dashboard', {
    headers: { Authorization: 'Bearer ' + token },
    cache: 'no-store'
  });
}

function load() {
  request(base)
    .catch(function () {
      if (base === API_BASE) {
        base = API_FALLBACK;
        return request(base);
      }
      throw new Error('unreachable');
    })
    .then(function (response) {
      if (response.status === 401) {
        clearToken();
        showGate(true);
        return null;
      }
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    })
    .then(function (data) {
      if (!data) return;
      showApp();
      render(data);
      el('beacon').setAttribute('data-state', 'live');
      text(el('stamp'), 'mise à jour ' + clockTime(data.generated_at));
      el('banner').hidden = true;
    })
    .catch(function (err) {
      el('beacon').setAttribute('data-state', 'down');
      text(el('stamp'), 'hors ligne');
      var banner = el('banner');
      banner.hidden = false;
      text(banner, 'Le serveur de supervision ne répond pas (' + err.message +
        '). Vérifie que dashboard_api.py tourne sur le NAS.');
    });
}

function start() {
  showApp();
  load();
  if (timer) clearInterval(timer);
  timer = setInterval(load, REFRESH_MS);
}

/* ------------------------------------------------------------------ */
/* render                                                              */
/* ------------------------------------------------------------------ */

function render(data) {
  renderServices(data.services, data.library);
  renderMeters(data.system, data.music_folder);
  renderNowPlaying(data.now_playing);
  renderLibrary(data.library, data.music_folder);
  renderUsers(data.users);
  renderRecent(data.recent_albums);
  renderPlaylists(data.playlists);
  renderLogs(data.logs);
  renderFooter(data, base);
}

function setService(id, label, state, meta) {
  var cell = el(id);
  cell.setAttribute('data-state', state);
  cell.querySelector('.svc-state').textContent = label;
  cell.querySelector('.svc-meta').textContent = meta;
}

function renderServices(services, library) {
  if (!services || services.error) {
    setService('svcNavidrome', 'inconnu', 'down', '');
    setService('svcUpload', 'inconnu', 'down', '');
    return;
  }

  var nav = services.navidrome || {};
  setService(
    'svcNavidrome',
    nav.running ? (nav.http ? 'en service' : 'ne répond pas') : 'arrêté',
    nav.running && nav.http ? 'up' : (nav.running ? 'warn' : 'down'),
    nav.running ? 'pid ' + nav.pid + ' · ' + duration(nav.uptime_seconds) + ' · ' + bytes(nav.rss_bytes) : ''
  );

  var up = services.upload_server || {};
  setService(
    'svcUpload',
    up.running ? (up.http ? 'en service' : 'ne répond pas') : 'arrêté',
    up.running && up.http ? 'up' : (up.running ? 'warn' : 'down'),
    up.running ? 'pid ' + up.pid + ' · ' + duration(up.uptime_seconds) + ' · ' + bytes(up.rss_bytes) : ''
  );

  var dash = services.dashboard || {};
  setService('svcDashboard', 'en service', 'up', 'pid ' + dash.pid + ' · ' + duration(dash.uptime_seconds));

  if (library && !library.error) {
    setService(
      'svcScan',
      library.scanning ? 'analyse en cours' : 'au repos',
      library.scanning ? 'warn' : 'up',
      library.last_scan ? 'dernière analyse ' + shortDate(library.last_scan) : ''
    );
  } else {
    setService('svcScan', 'inconnu', 'down', library && library.error ? library.error : '');
  }
}

function paintMeter(id, opts) {
  var node = el(id);
  node.querySelector('.meter-value').textContent = opts.value;
  node.querySelector('.meter-foot').textContent = opts.foot;
  var fill = node.querySelector('.gauge i');
  fill.style.width = Math.max(0, Math.min(100, opts.percent || 0)) + '%';
  fill.setAttribute('data-level', opts.level || 'ok');
}

function renderMeters(system, music) {
  system = system || {};
  var vol = system.volume || {};
  if (vol.error || vol.total_bytes === undefined) {
    paintMeter('meterVolume', { value: '—', foot: vol.error || 'indisponible', percent: 0 });
  } else {
    paintMeter('meterVolume', {
      value: vol.percent + ' %',
      foot: bytes(vol.used_bytes) + ' utilisés · ' + bytes(vol.free_bytes) + ' libres',
      percent: vol.percent,
      level: level(vol.percent)
    });
  }

  var mem = system.memory || {};
  if (mem.error || mem.total_bytes === undefined) {
    paintMeter('meterMemory', { value: '—', foot: mem.error || 'indisponible', percent: 0 });
  } else {
    paintMeter('meterMemory', {
      value: mem.percent + ' %',
      foot: bytes(mem.used_bytes) + ' sur ' + bytes(mem.total_bytes),
      percent: mem.percent,
      level: level(mem.percent)
    });
  }

  if (!music || music.pending) {
    paintMeter('meterMusic', { value: '…', foot: 'analyse du dossier en cours', percent: 0 });
  } else if (music.error) {
    paintMeter('meterMusic', { value: '—', foot: music.error, percent: 0 });
  } else {
    var share = vol.used_bytes ? (music.total_bytes / vol.used_bytes) * 100 : 0;
    paintMeter('meterMusic', {
      value: bytes(music.total_bytes),
      foot: num(music.file_count) + ' fichiers · ' + Math.round(share) + ' % du volume occupé',
      percent: share,
      level: 'ok'
    });
  }

  var load = system.load || {};
  if (load.error || load.load_1 === undefined) {
    paintMeter('meterLoad', { value: '—', foot: 'indisponible', percent: 0 });
  } else {
    /* DS218 is dual-core, so a load of 2.0 saturates it. */
    var pct = Math.min(100, (load.load_1 / 2) * 100);
    paintMeter('meterLoad', {
      value: load.load_1.toFixed(2),
      foot: '5 min ' + load.load_5.toFixed(2) + ' · 15 min ' + load.load_15.toFixed(2) +
            ' · actif depuis ' + duration(load.uptime_seconds),
      percent: pct,
      level: level(pct)
    });
  }
}

function renderNowPlaying(entries) {
  var host = el('nowPlaying');
  host.innerHTML = '';

  if (!entries || entries.error || !entries.length) {
    var p = document.createElement('p');
    p.className = 'empty';
    p.textContent = entries && entries.error
      ? 'Impossible de lire les lectures en cours : ' + entries.error
      : 'Personne n\u2019écoute en ce moment.';
    host.appendChild(p);
    return;
  }

  entries.forEach(function (entry) {
    var row = document.createElement('div');
    row.className = 'playing-row';

    var who = document.createElement('span');
    who.className = 'playing-who';
    who.textContent = entry.username || '—';

    var track = document.createElement('span');
    track.className = 'playing-track';
    track.textContent = entry.title || '—';
    var by = document.createElement('em');
    by.textContent = entry.artist ? '  ·  ' + entry.artist : '';
    track.appendChild(by);

    var when = document.createElement('span');
    when.className = 'playing-when';
    var ago = entry.minutes_ago === 0 ? 'à l\u2019instant' : 'il y a ' + entry.minutes_ago + ' min';
    when.textContent = entry.player ? entry.player + ' · ' + ago : ago;

    row.appendChild(who);
    row.appendChild(track);
    row.appendChild(when);
    host.appendChild(row);
  });
}

function figure(value, label) {
  var wrap = document.createElement('div');
  var v = document.createElement('span');
  v.className = 'figure-value';
  v.textContent = value;
  var l = document.createElement('span');
  l.className = 'figure-label';
  l.textContent = label;
  wrap.appendChild(v);
  wrap.appendChild(l);
  return wrap;
}

var FORMAT_COLORS = ['#2f5170', '#2e6b4c', '#8f6412', '#a3382a', '#6b4f7a', '#3d6f75', '#7a6a4f'];

function renderLibrary(library, music) {
  var host = el('figures');
  host.innerHTML = '';

  if (library && !library.error) {
    host.appendChild(figure(num(library.tracks), 'morceaux'));
    host.appendChild(figure(num(library.albums), 'albums'));
    host.appendChild(figure(num(library.artists), 'artistes'));
    host.appendChild(figure(num(library.folders), 'dossiers'));
  }
  if (music && !music.pending && !music.error) {
    host.appendChild(figure(num(music.lyrics_files), 'fichiers .lrc'));
  }

  var box = el('formats');
  box.innerHTML = '';
  if (!music || music.pending || music.error || !music.formats || !music.formats.length) {
    var p = document.createElement('p');
    p.className = 'empty';
    p.textContent = music && music.pending
      ? 'Répartition par format en cours de calcul (première analyse du dossier).'
      : 'Répartition par format indisponible.';
    box.appendChild(p);
    return;
  }

  var total = music.formats.reduce(function (sum, f) { return sum + f.bytes; }, 0) || 1;

  var bar = document.createElement('div');
  bar.className = 'format-bar';
  var legend = document.createElement('ul');
  legend.className = 'format-legend';

  music.formats.forEach(function (f, i) {
    var color = FORMAT_COLORS[i % FORMAT_COLORS.length];
    var share = (f.bytes / total) * 100;

    var seg = document.createElement('span');
    seg.style.width = share + '%';
    seg.style.background = color;
    seg.title = f.ext + ' · ' + bytes(f.bytes);
    bar.appendChild(seg);

    var li = document.createElement('li');
    var sw = document.createElement('i');
    sw.className = 'swatch';
    sw.style.background = color;
    var name = document.createElement('span');
    name.textContent = '.' + f.ext;
    var val = document.createElement('b');
    val.textContent = bytes(f.bytes) + ' (' + num(f.count) + ')';
    li.appendChild(sw);
    li.appendChild(name);
    li.appendChild(val);
    legend.appendChild(li);
  });

  box.appendChild(bar);
  box.appendChild(legend);
}

function renderUsers(users) {
  var body = el('usersTable').querySelector('tbody');
  body.innerHTML = '';

  if (!users || users.error || !users.length) {
    var row = body.insertRow();
    var cell = row.insertCell();
    cell.colSpan = 3;
    cell.className = 'dim';
    cell.textContent = users && users.error
      ? 'Lecture impossible : ' + users.error + ' (le compte doit être administrateur)'
      : 'Aucun compte.';
    text(el('usersCount'), '');
    return;
  }

  text(el('usersCount'), users.length);

  users.forEach(function (user) {
    var row = body.insertRow();
    row.insertCell().textContent = user.username || '—';

    var mail = row.insertCell();
    mail.className = 'dim';
    mail.textContent = user.email || '—';

    var rights = row.insertCell();
    [['admin', user.admin], ['import', user.download],
     ['playlists', user.playlist], ['partage', user.share]].forEach(function (pair) {
      if (!pair[1]) return;
      var tag = document.createElement('span');
      tag.className = 'tag on';
      tag.textContent = pair[0];
      rights.appendChild(tag);
    });
    if (!rights.childNodes.length) rights.textContent = '—';
  });
}

function renderRecent(albums) {
  var list = el('recentAlbums');
  list.innerHTML = '';

  if (!albums || albums.error || !albums.length) {
    var li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'Aucun album récent.';
    list.appendChild(li);
    return;
  }

  albums.forEach(function (album) {
    var li = document.createElement('li');
    var title = document.createElement('div');
    title.textContent = album.name || '—';
    var meta = document.createElement('span');
    meta.textContent = (album.artist || '—') + ' · ' + shortDate(album.created);
    li.appendChild(title);
    li.appendChild(meta);
    list.appendChild(li);
  });
}

function renderPlaylists(playlists) {
  var body = el('playlistsTable').querySelector('tbody');
  body.innerHTML = '';

  if (!playlists || playlists.error || !playlists.length) {
    var row = body.insertRow();
    var cell = row.insertCell();
    cell.colSpan = 5;
    cell.className = 'dim';
    cell.textContent = playlists && playlists.error
      ? 'Lecture impossible : ' + playlists.error
      : 'Aucune playlist.';
    text(el('playlistsCount'), '');
    return;
  }

  var totalSongs = playlists.reduce(function (s, p) { return s + (p.songs || 0); }, 0);
  text(el('playlistsCount'), playlists.length + ' · ' + num(totalSongs) + ' entrées');

  playlists.forEach(function (pl) {
    var row = body.insertRow();
    row.insertCell().textContent = pl.name || '—';

    var owner = row.insertCell();
    owner.className = 'dim';
    owner.textContent = pl.owner || '—';

    var songs = row.insertCell();
    songs.className = 'num';
    songs.textContent = num(pl.songs);

    var dur = row.insertCell();
    dur.className = 'num';
    dur.textContent = duration(pl.duration);

    var changed = row.insertCell();
    changed.className = 'dim';
    changed.textContent = shortDate(pl.changed);
  });
}

function paintLog(node, lines) {
  node.innerHTML = '';
  if (!lines || !lines.length) {
    node.textContent = 'Journal vide ou introuvable.';
    return;
  }
  lines.forEach(function (line) {
    if (/\b(ERROR|FATAL|panic)\b/.test(line)) {
      var b = document.createElement('b');
      b.textContent = line;
      node.appendChild(b);
    } else {
      node.appendChild(document.createTextNode(line));
    }
    node.appendChild(document.createTextNode('\n'));
  });
  node.scrollTop = node.scrollHeight;
}

function renderLogs(logs) {
  logs = logs || {};
  paintLog(el('logNavidrome'), logs.navidrome);
  paintLog(el('logUpload'), logs.upload_server);
  var errors = logs.navidrome_errors || 0;
  text(el('logErrors'), errors ? errors + ' erreurs récentes' : '');
}

function renderFooter(data, host) {
  var music = data.music_folder || {};
  var note = 'source ' + host + ' · rafraîchissement ' + (REFRESH_MS / 1000) + ' s';
  if (music.scanned_at) {
    note += ' · dossier analysé ' + clockTime(music.scanned_at);
    if (music.refreshing) note += ' (réanalyse en cours)';
  }
  text(el('footerNote'), note);
}

/* ------------------------------------------------------------------ */
/* boot                                                                */
/* ------------------------------------------------------------------ */

document.addEventListener('DOMContentLoaded', function () {
  el('tokenSubmit').addEventListener('click', submitToken);
  el('tokenInput').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') submitToken();
  });
  el('forget').addEventListener('click', function () {
    clearToken();
    token = '';
    showGate(false);
  });

  token = readToken();
  if (token) start(); else showGate(false);
});
