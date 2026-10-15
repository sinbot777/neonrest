(() => {
  'use strict';
  const prefs = window.NEON_MEDIA_PREFS || {gif_mode: 'system', midi_autoplay: 0};
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const defaultGif = prefs.gif_mode === 'system' ? (reduced ? 'off' : 'once') : prefs.gif_mode;

  document.querySelectorAll('.gif-card').forEach(card => {
    const image = card.querySelector('img');
    let mode = defaultGif;
    let playing = false;
    const loopButton = card.querySelector('[data-gif-action="loop"]');
    const show = (choice, restart = false) => {
      mode = choice;
      playing = choice !== 'off';
      image.src = card.dataset[choice === 'loop' ? 'loop' : choice === 'once' ? 'once' : 'poster'] +
        (restart ? '?again=' + Date.now() : '');
      loopButton.setAttribute('aria-pressed', String(choice === 'loop'));
    };
    show(mode);
    card.addEventListener('click', event => {
      const action = event.target.closest('[data-gif-action]')?.dataset.gifAction;
      if (!action) return;
      if (action === 'pause') show('off');
      if (action === 'loop') show(mode === 'loop' ? 'once' : 'loop', true);
      if (action === 'play' || action === 'replay') show(mode === 'loop' ? 'loop' : 'once', true);
    });
  });

  function midiNotes(buffer) {
    const bytes = new Uint8Array(buffer);
    const view = new DataView(buffer);
    const word = pos => view.getUint16(pos);
    const long = pos => view.getUint32(pos);
    const text = (pos, length) => String.fromCharCode(...bytes.slice(pos, pos + length));
    if (text(0, 4) !== 'MThd' || long(4) !== 6) throw Error('Invalid MIDI file');
    const tracks = word(10), division = word(12);
    let pos = 14;
    const events = [];
    function vlq(end) {
      let value = 0;
      for (let i = 0; i < 4; i++) {
        if (pos >= end) throw Error('Truncated MIDI file');
        const b = bytes[pos++]; value = value * 128 + (b & 127);
        if (!(b & 128)) return value;
      }
      throw Error('Invalid MIDI length');
    }
    for (let track = 0; track < tracks; track++) {
      if (text(pos, 4) !== 'MTrk') throw Error('Invalid MIDI track');
      const end = pos + 8 + long(pos + 4);
      pos += 8;
      let tick = 0, running = 0;
      while (pos < end) {
        tick += vlq(end);
        let status = bytes[pos];
        if (status & 128) { pos++; if (status < 240) running = status; }
        else status = running;
        if (status === 255) {
          const kind = bytes[pos++], size = vlq(end);
          if (kind === 81 && size === 3) events.push({tick, type: 'tempo', value: bytes[pos] * 65536 + bytes[pos + 1] * 256 + bytes[pos + 2]});
          pos += size;
        } else if (status === 240 || status === 247) pos += vlq(end);
        else if (status >= 128 && status < 240) {
          const op = status & 240, channel = status & 15;
          const a = bytes[pos++], b = (op === 192 || op === 208) ? 0 : bytes[pos++];
          if (op === 144 && b) events.push({tick, type: 'on', channel, pitch: a, velocity: b});
          if (op === 128 || (op === 144 && !b)) events.push({tick, type: 'off', channel, pitch: a});
        } else throw Error('Unsupported MIDI event');
      }
      pos = end;
    }
    const order = {tempo: 0, off: 1, on: 2};
    events.sort((a, b) => a.tick - b.tick || order[a.type] - order[b.type]);
    let tick = 0, seconds = 0, tempo = 500000;
    const active = new Map(), notes = [];
    for (const event of events) {
      seconds += (event.tick - tick) * tempo / (division * 1000000);
      tick = event.tick;
      if (event.type === 'tempo') { tempo = event.value; continue; }
      const key = event.channel + ':' + event.pitch;
      if (event.type === 'on') active.set(key, {start: seconds, pitch: event.pitch, channel: event.channel, velocity: event.velocity});
      else if (active.has(key)) {
        const note = active.get(key); note.end = Math.max(seconds, note.start + .05); notes.push(note); active.delete(key);
      }
    }
    notes.sort((a, b) => a.start - b.start);
    // Metadata tracks can extend far beyond the last audible note.
    const audibleEnd = notes.reduce((latest, note) => Math.max(latest, note.end), 0);
    return {notes, duration: Math.min(audibleEnd, 600)};
  }

  let context, current = null, pausedCard = null;
  function label(card, verb) {
    const button = card.querySelector('.midi-play');
    const title = button.getAttribute('aria-label').replace(/^(Play|Pause) /, '');
    button.textContent = verb;
    button.setAttribute('aria-label', verb + ' ' + title);
  }
  function silence(card) {
    clearInterval(card.timer);
    card.timer = null;
    (card.voices || []).forEach(voice => { try { voice.stop(); } catch (_) {} });
    card.voices = [];
  }
  function stop(card) {
    if (!card) return;
    silence(card);
    card.pausedAt = 0;
    card.isPaused = false;
    card.index = 0;
    label(card, 'Play');
    card.querySelector('.midi-status').textContent = '';
    if (current === card) current = null;
    if (pausedCard === card) pausedCard = null;
  }
  function pause(card) {
    if (!card || current !== card) return;
    card.pausedAt = Math.max(0, Math.min(card.score.duration, context.currentTime - card.started));
    silence(card);
    card.isPaused = true;
    current = null;
    pausedCard = card;
    label(card, 'Play');
    card.querySelector('.midi-status').textContent = 'Paused';
  }
  function draw(card, notes, duration) {
    const canvas = card.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#191826'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!duration) return;
    ctx.fillStyle = '#83daba';
    notes.forEach(note => ctx.fillRect(note.start / duration * canvas.width,
      (108 - note.pitch) / 96 * canvas.height,
      Math.max(2, (note.end - note.start) / duration * canvas.width), 2));
  }
  async function load(card) {
    if (card.score) return card.score;
    const response = await fetch(card.dataset.midiSrc);
    if (!response.ok) throw Error('Could not load MIDI');
    const score = midiNotes(await response.arrayBuffer());
    card.score = score;
    card.querySelector('.midi-duration').textContent = Math.round(score.duration / 60) + ':' + String(Math.round(score.duration % 60)).padStart(2, '0');
    draw(card, score.notes, score.duration);
    return score;
  }
  async function play(card, automatic = false) {
    try {
      const score = await load(card);
      context ||= new (window.AudioContext || window.webkitAudioContext)();
      await context.resume();
      if (context.state !== 'running') throw Error('Click Enable sound to play');
      if (current) stop(current);
      if (pausedCard && pausedCard !== card) stop(pausedCard);
      const offset = card.isPaused ? card.pausedAt : 0;
      current = card;
      pausedCard = null;
      card.isPaused = false;
      card.voices = [];
      card.index = score.notes.findIndex(note => note.end > offset);
      if (card.index < 0) card.index = score.notes.length;
      const started = context.currentTime + .05 - offset;
      card.started = started;
      function schedule() {
        if (current !== card) return;
        const horizon = context.currentTime + .35 - started;
        while (card.index < score.notes.length && score.notes[card.index].start < horizon) {
          const note = score.notes[card.index++];
          if (note.channel === 9 || note.end <= context.currentTime - started) continue;
          const oscillator = context.createOscillator();
          const gain = context.createGain();
          oscillator.type = 'triangle';
          oscillator.frequency.value = 440 * 2 ** ((note.pitch - 69) / 12);
          oscillator.connect(gain).connect(context.destination);
          const start = Math.max(context.currentTime, started + note.start);
          const end = Math.max(start + .05, started + note.end);
          gain.gain.setValueAtTime(0, start);
          gain.gain.linearRampToValueAtTime(Math.min(.18, note.velocity / 700), start + .012);
          gain.gain.setValueAtTime(Math.min(.18, note.velocity / 700), Math.max(start + .012, end - .04));
          gain.gain.linearRampToValueAtTime(0, end);
          oscillator.start(start); oscillator.stop(end + .02);
          card.voices.push(oscillator);
        }
        if (context.currentTime - started > score.duration + .2) stop(card);
      }
      schedule(); card.timer = setInterval(schedule, 100);
      label(card, 'Pause');
      card.querySelector('.midi-status').textContent = 'Playing';
    } catch (error) {
      card.querySelector('.midi-status').textContent = automatic ? 'Click Play to enable sound' : error.message;
    }
  }
  const cards = [...document.querySelectorAll('.midi-card')];
  cards.forEach(card => {
    card.querySelector('.midi-play').addEventListener('click', () => current === card ? pause(card) : play(card));
    card.querySelector('.midi-stop').addEventListener('click', () => stop(card));
    load(card).catch(() => { card.querySelector('.midi-status').textContent = 'MIDI unavailable'; });
  });
  if (prefs.midi_autoplay && cards.length) {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting && entry.intersectionRatio >= .6 && !current && !entry.target.autoplayAttempted) {
          entry.target.autoplayAttempted = true;
          play(entry.target, true);
        } else if (!entry.isIntersecting && current === entry.target) stop(current);
      });
    }, {threshold: [.6]});
    cards.forEach(card => observer.observe(card));
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(current); });
})();
