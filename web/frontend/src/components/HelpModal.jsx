import styles from './HelpModal.module.css'

function Section({ icon, title, children }) {
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}><span className={styles.icon}>{icon}</span>{title}</h3>
      <div className={styles.sectionBody}>{children}</div>
    </section>
  )
}

export default function HelpModal({ onClose, isAdmin = false, voiceControl = false, presenceRequired = false, appTitle = 'the bot' }) {
  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <h2 className={styles.title}>How to use {appTitle}</h2>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>

        <div className={styles.body}>
          <p className={styles.intro}>
            Browse the soundboard, then play clips into the voice channel. Here's a quick tour.
          </p>

          <Section icon="▶" title="Playing a clip">
            Hit <b>▶</b> on any clip card to play it in the channel. Use the <b>Pitch</b> and
            <b> Speed</b> sliders first to change how it sounds — your settings are remembered
            per clip. Multiple people can fire clips at once; they overlap like a real soundboard.
            Click the clip name to <b>preview it in your browser</b>, or <b>⬇</b> to download the file.
            {presenceRequired && (
              <p className={styles.note}>
                ⚠ You must be <b>in the voice channel</b> and linked to your account by an admin
                before you can play. If you see a "not linked" banner, ask an admin.
              </p>
            )}
          </Section>

          <Section icon="🔎" title="Finding clips">
            Search by <b>name, ID, or tag</b> (typing "foo" matches a clip called <i>foo</i> or
            anything tagged <i>footy</i>). Filter by a <b>tag</b> or toggle <b>★ Favourites</b> to
            narrow the list.
          </Section>

          <Section icon="↕" title="Sorting & layout">
            Choose how clips are ordered:
            <ul className={styles.list}>
              <li><b>A→Z</b> — alphabetical by name.</li>
              <li><b>Date ↓</b> — most recently uploaded first.</li>
              <li><b>Date ↑</b> — oldest uploaded first.</li>
              <li><b>★ Top</b> — highest rated (most up-votes) first.</li>
              <li><b>🥀 Rot</b> — lowest rated first.</li>
            </ul>
            And how they're laid out:
            <ul className={styles.list}>
              <li><b>⊞ Grid</b> — cards with full controls.</li>
              <li><b>☰ List</b> — compact rows, more on screen at once.</li>
              <li><b>▦ Pads</b> — your favourites as a hotkey soundboard (below).</li>
            </ul>
          </Section>

          <Section icon="👂" title="Preview privately">
            Click a clip's <b>name</b> to hear it <b>in your own browser only</b> — it won't play
            to the channel. Click again to stop. Great for checking before you blast it.
          </Section>

          <Section icon="▦" title="Pad board & hotkeys">
            Star clips with <b>☆</b>, then switch to the <b>▦ pad view</b>: your favourites become
            big pads. The first ten are bound to keys <b>1–9, 0</b> — tap a pad or press its key to
            fire it (with that pad's pitch/speed). There's a gentle limit of <b>10 plays per 30s</b>
            to stop runaway spamming.
          </Section>

          <Section icon="≡" title="Queues">
            Hit <b>+</b> on a clip to add it to a queue (in the sidebar). Play the whole queue as one
            burst. After playing a queue there's a <b>10-second cooldown</b> before the next one.
          </Section>

          <Section icon="▲" title="Voting & favourites">
            <b>▲ / ▼</b> up- or down-vote clips (a shared tally everyone sees). <b>☆ / ★</b> marks
            your personal favourites, which also become your pad board.
          </Section>

          <Section icon="↑" title="Uploading">
            Use <b>↑ Upload</b> to add a clip (.wav / .mp3). You can drop in a file up to <b>60s</b>
            and <b>drag the handles on the waveform to trim it down</b> to the ≤10s you want to keep —
            only the selection is uploaded. Preview the whole file or just your selection before you
            commit. Uploads are loudness-normalised so nothing is wildly louder than the rest.
          </Section>

          <Section icon="✎" title="Editing your clips">
            On clips you uploaded (admins can edit any), the <b>✎</b> button lets you <b>rename</b> and
            change <b>tags</b>, and open <b>✂ Trim audio</b> — drag the handles on the waveform to cut
            the clip, preview the selection, then trim. The original is backed up so you can
            <b> revert</b>. Votes and history are kept.
            {isAdmin && (
              <> Admins also get a <b>Volume</b> slider here (−12 to +12 dB) to manually fine-tune
              a clip that's still too loud or too quiet after loudness normalisation — it's applied
              live at playback, so it's non-destructive and re-adjustable any time.</>
            )}
          </Section>

          {voiceControl && (
            <Section icon="🔊" title="Moving the bot">
              Use the <b>Voice</b> panel to pick a channel and <b>Join</b> / <b>Leave</b>. The bot
              won't sit in an empty channel.
            </Section>
          )}

          <Section icon="♻" title="Bot laggy or stuck?">
            Hit <b>♻ Restart bot</b> (then confirm) to bounce it — it exits, comes straight back,
            and <b>rejoins the channel</b> it was in within a few seconds. Handy if playback gets
            laggy after the bot's been up a long time. It also restarts itself automatically twice
            a day. Everyone in the app sees a notice when it happens.
          </Section>

          <Section icon="📊" title="Stats">
            The <b>📊 Stats</b> page shows what's popular: clip of the week, a clickable clip cloud,
            top players, an activity heatmap, and drill-downs — click any clip or player to see their
            breakdown. Pick a time range at the top.
          </Section>

          {isAdmin && (
            <Section icon="🛠" title="Admin">
              <b>⚙ Users</b> links each web account to their voice identity (so presence checks work).
              <b> ⏹ Stop</b> instantly halts all playback and clears the queue — everyone sees a
              notification when you do.
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}
