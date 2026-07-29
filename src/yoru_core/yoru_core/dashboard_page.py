"""Embedded HTML page for the Yoru V3 admin dashboard (single file, no assets).

Apple "liquid glass" design: frosted translucent cards (backdrop blur) over a
soft aurora gradient, pill buttons, system font stack. Follows the device
light/dark setting automatically and is fully responsive for phones.

Screens (glass sidebar on desktop, bottom tab bar on phones):
  Setup   - first-time workflow: keyboard/joystick mapping drive, Save Map,
            click-to-mark CCTV camera spots on the map
  Control - live status, mode switch, e-stop, return-to-base, virtual joystick
  Cameras - live CCTV detection view + robot onboard camera + alert badge
  Map     - live map with robot pose, camera spots + violation target,
            tap-and-drag relocalise, clear-costmaps recovery
  History - violation statistics and metadata-only incident table

First run: the server has no admin password; the page shows a
"create password" screen instead of login (POST /api/setup).
"""

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#eef1f8">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0b0e14">
<title>Yoru Robot</title>
<style>
  :root {
    --bg1:#dfe7ff; --bg2:#ffe9f3; --bg3:#e3fff3; --base:#eef1f8;
    --glass:rgba(255,255,255,.58); --glass2:rgba(255,255,255,.42);
    --stroke:rgba(255,255,255,.65); --hairline:rgba(60,60,67,.12);
    --txt:#1c1c1e; --dim:rgba(60,60,67,.6);
    --blue:#007aff; --green:#34c759; --orange:#ff9500; --red:#ff3b30;
    --knob:rgba(255,255,255,.85); --shadow:0 8px 32px rgba(31,38,60,.12);
    --mapbg:rgba(255,255,255,.35);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg1:#1b2347; --bg2:#3a1d3f; --bg3:#0f2e33; --base:#0b0e14;
      --glass:rgba(28,32,44,.55); --glass2:rgba(28,32,44,.4);
      --stroke:rgba(255,255,255,.14); --hairline:rgba(255,255,255,.1);
      --txt:#f2f3f7; --dim:rgba(235,235,245,.55);
      --blue:#0a84ff; --green:#30d158; --orange:#ff9f0a; --red:#ff453a;
      --knob:rgba(255,255,255,.22); --shadow:0 8px 32px rgba(0,0,0,.45);
      --mapbg:rgba(255,255,255,.07);
    }
  }
  * { box-sizing:border-box; margin:0; min-width:0;
      -webkit-tap-highlight-color:transparent; }
  html { font-size:16px; }
  body {
    min-height:100vh; color:var(--txt); background:var(--base);
    overflow-x:hidden; max-width:100vw;
    font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','SF Pro Text',
                'Segoe UI',Roboto,'Helvetica Neue',sans-serif;
  }
  body::before {
    content:''; position:fixed; inset:-20%; z-index:-1;
    background:
      radial-gradient(40% 50% at 15% 15%, var(--bg1) 0%, transparent 70%),
      radial-gradient(45% 55% at 85% 20%, var(--bg2) 0%, transparent 70%),
      radial-gradient(50% 60% at 50% 95%, var(--bg3) 0%, transparent 70%),
      var(--base);
    filter:blur(40px); animation:drift 24s ease-in-out infinite alternate;
  }
  @keyframes drift {
    from { transform:translate(0,0) scale(1); }
    to   { transform:translate(2%,3%) scale(1.06); }
  }

  .glass {
    background:var(--glass);
    -webkit-backdrop-filter:blur(28px) saturate(180%);
    backdrop-filter:blur(28px) saturate(180%);
    border:1px solid var(--stroke); border-radius:24px;
    box-shadow:var(--shadow);
  }

  /* ---------- app shell: sidebar + content ---------- */
  #app { display:flex; min-height:100vh; }
  aside {
    width:218px; flex:none; margin:14px 0 14px 14px; padding:18px 12px;
    display:flex; flex-direction:column; gap:6px;
    position:sticky; top:14px; height:calc(100vh - 28px);
    border-radius:26px;
  }
  aside .brand { display:flex; align-items:center; gap:10px;
                 padding:6px 10px 16px; }
  aside .brand .dot { width:36px; height:36px; border-radius:11px; flex:none;
    background:linear-gradient(135deg,var(--blue),#5e5ce6);
    display:flex; align-items:center; justify-content:center;
    color:#fff; font-size:19px; }
  aside .brand h1 { font-size:15px; font-weight:700; letter-spacing:-.02em; }
  aside .brand p { font-size:11px; color:var(--dim); }
  .navbtn {
    display:flex; align-items:center; gap:12px; width:100%;
    padding:12px 14px; border-radius:14px; border:none; background:none;
    font-family:inherit; font-size:14.5px; font-weight:600; color:var(--dim);
    cursor:pointer; text-align:left; transition:background .15s;
  }
  .navbtn .ic { font-size:18px; width:24px; text-align:center; }
  .navbtn.active { background:var(--glass2); color:var(--txt);
                   border:1px solid var(--stroke); }
  aside .spacer { flex:1; }
  aside .modechip { text-align:center; }

  main { flex:1; padding:14px; max-width:1100px;
         padding-bottom:max(20px, env(safe-area-inset-bottom)); }
  .topbar { display:flex; align-items:center; gap:12px; padding:14px 20px;
            margin-bottom:12px; }
  .topbar h2 { font-size:17px; font-weight:700; letter-spacing:-.02em; flex:1; }

  .badge { padding:6px 14px; border-radius:100px; font-size:13px;
           font-weight:600; letter-spacing:.01em; display:inline-block; }
  .b-auto   { background:rgba(52,199,89,.16); color:var(--green); }
  .b-manual { background:rgba(255,149,0,.18); color:var(--orange); }
  .b-alert  { background:rgba(255,69,58,.18); color:var(--red); }

  .grid { display:grid; gap:10px;
          grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr)); }
  .stat { padding:16px 18px; border-radius:20px; }
  .stat .label { font-size:12px; color:var(--dim); font-weight:500;
                 margin-bottom:5px; }
  .stat .value { font-size:22px; font-weight:700; letter-spacing:-.02em; }
  .stat .value.small { font-size:17px; }
  .ok { color:var(--green); } .off { color:var(--dim); }
  .bad { color:var(--red); }

  .row { display:grid; gap:12px; margin-top:12px;
         grid-template-columns:repeat(auto-fit,minmax(min(310px,100%),1fr)); }
  .panel { padding:20px; }
  .panel h2 { font-size:13px; font-weight:600; color:var(--dim);
              text-transform:uppercase; letter-spacing:.06em;
              margin-bottom:14px; }

  button {
    font-family:inherit; font-size:16px; font-weight:600; color:var(--txt);
    background:var(--glass2); border:1px solid var(--stroke);
    border-radius:100px; padding:14px 20px; cursor:pointer;
    min-height:48px; transition:transform .12s ease, filter .15s ease;
    -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  }
  button:active { transform:scale(.96); filter:brightness(1.08); }
  button.primary { background:var(--blue); border-color:transparent; color:#fff;
                   box-shadow:0 6px 20px rgba(10,132,255,.35); }
  button.danger  { background:var(--red); border-color:transparent; color:#fff;
                   box-shadow:0 6px 20px rgba(255,69,58,.35); }
  button.success { background:var(--green); border-color:transparent; color:#fff;
                   box-shadow:0 6px 20px rgba(52,199,89,.35); }
  button.warn.on { background:var(--orange); border-color:transparent;
                   color:#fff; box-shadow:0 6px 20px rgba(255,149,0,.35); }
  .btnrow { display:flex; flex-direction:column; gap:10px; }
  .btnrow button { width:100%; }
  .note { font-size:12.5px; color:var(--dim); margin-top:12px; line-height:1.5; }

  /* Setup checklist */
  .steps { display:flex; flex-direction:column; gap:9px; }
  .step { display:flex; align-items:center; gap:11px; font-size:14px;
          font-weight:600; }
  .step .tick { width:26px; height:26px; border-radius:50%; flex:none;
    display:flex; align-items:center; justify-content:center; font-size:14px;
    background:var(--glass2); border:1px solid var(--stroke); color:var(--dim); }
  .step.done .tick { background:var(--green); color:#fff; border-color:transparent; }
  .step.done { color:var(--dim); text-decoration:line-through; }

  /* Keyboard drive keys */
  .keypad { display:grid; grid-template-columns:repeat(3,64px); gap:8px;
            justify-content:center; margin:8px 0 4px; }
  .key { width:64px; height:54px; border-radius:14px; min-height:0;
         padding:0; font-size:19px; user-select:none; touch-action:none; }
  .key.pressed { background:var(--blue); color:#fff; border-color:transparent; }
  .key.ghost { visibility:hidden; }

  /* Virtual joystick */
  .stickwrap { display:flex; flex-direction:column; align-items:center; }
  #stick {
    width:200px; height:200px; border-radius:50%; position:relative;
    background:var(--glass2); border:1px solid var(--stroke);
    -webkit-backdrop-filter:blur(16px); backdrop-filter:blur(16px);
    touch-action:none; box-shadow:inset 0 2px 14px rgba(0,0,0,.08);
  }
  #stick::before { content:''; position:absolute; inset:14px;
    border-radius:50%; border:1.5px dashed var(--hairline); }
  #knob {
    width:84px; height:84px; border-radius:50%; position:absolute;
    left:58px; top:58px; background:var(--knob);
    border:1px solid var(--stroke);
    box-shadow:0 6px 18px rgba(0,0,0,.22);
    -webkit-backdrop-filter:blur(8px); backdrop-filter:blur(8px);
    transition:left .25s cubic-bezier(.3,1.4,.5,1), top .25s cubic-bezier(.3,1.4,.5,1);
    display:flex; align-items:center; justify-content:center;
    color:var(--dim); font-size:24px; user-select:none;
  }
  #knob.live { transition:none; }

  /* Map screens */
  .mapbox { position:relative; border-radius:18px; overflow:hidden;
            background:var(--mapbg); touch-action:none; }
  .mapbox canvas { display:block; width:100%; }
  .maphint { position:absolute; left:0; right:0; top:10px; text-align:center;
             pointer-events:none; }
  .maphint span { background:var(--glass); border:1px solid var(--stroke);
    border-radius:100px; padding:7px 16px; font-size:13px; font-weight:600;
    -webkit-backdrop-filter:blur(14px); backdrop-filter:blur(14px); }
  .maptools { display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; }
  .maptools button { flex:1; min-width:150px; font-size:14.5px; }
  #toast { position:fixed; left:50%; bottom:90px; transform:translateX(-50%);
    background:var(--glass); border:1px solid var(--stroke);
    -webkit-backdrop-filter:blur(20px); backdrop-filter:blur(20px);
    border-radius:100px; padding:11px 20px; font-size:14px; font-weight:600;
    box-shadow:var(--shadow); opacity:0; transition:opacity .25s;
    pointer-events:none; z-index:60; max-width:90vw; text-align:center; }
  #toast.show { opacity:1; }

  /* Camera / base spot modals */
  #cammodal, #basemodal { position:fixed; inset:0; z-index:70; display:none;
              align-items:center; justify-content:center;
              background:rgba(0,0,0,.35); }
  #cammodal.show, #basemodal.show { display:flex; }
  #cammodal .card, #basemodal .card { width:min(360px, 92vw); padding:24px; }
  #cammodal h3, #basemodal h3 { font-size:17px; font-weight:700; margin-bottom:14px; }
  #cammodal label, #basemodal label { font-size:12px; color:var(--dim); font-weight:600;
                    display:block; margin:10px 0 4px; }
  #cammodal input, #cammodal select, #basemodal input {
    width:100%; padding:12px 14px; font-size:15px; font-family:inherit;
    color:var(--txt); background:var(--glass2);
    border:1px solid var(--stroke); border-radius:14px; outline:none;
  }
  #cammodal .btns, #basemodal .btns { display:flex; gap:10px; margin-top:18px; }
  #cammodal .btns button, #basemodal .btns button { flex:1; }

  .camlist { margin-top:12px; }
  .camrow { display:flex; align-items:center; gap:10px; padding:10px 4px;
            border-bottom:1px solid var(--hairline); font-size:14px; }
  .camrow:last-child { border-bottom:none; }
  .camrow .ic { font-size:17px; }
  .camrow .nm { font-weight:600; flex:1; }
  .camrow .xy { color:var(--dim); font-size:12.5px; }
  .camrow button { min-height:0; padding:7px 13px; font-size:12.5px; }

  /* Camera feeds */
  .feedbox { border-radius:18px; overflow:hidden; background:var(--mapbg);
             position:relative; min-height:120px; }
  .feedbox img { display:block; width:100%; }
  .feedbox .tag { position:absolute; top:10px; left:10px; }
  .feedbox .nosig { position:absolute; inset:0; display:flex;
    align-items:center; justify-content:center; color:var(--dim);
    font-size:13.5px; font-weight:600; }

  .tablewrap { overflow-x:auto; -webkit-overflow-scrolling:touch;
               border-radius:16px; }
  table { width:100%; border-collapse:collapse; font-size:13.5px;
          min-width:620px; }
  th, td { text-align:left; padding:10px 12px;
           border-bottom:1px solid var(--hairline); white-space:nowrap; }
  th { color:var(--dim); font-weight:600; font-size:12px;
       text-transform:uppercase; letter-spacing:.05em; }
  tr:last-child td { border-bottom:none; }
  td.outcome { font-weight:600; }
  tr.complied td.outcome { color:var(--green); }
  tr.failed   td.outcome { color:var(--red); }

  select {
    font-family:inherit; font-size:14px; color:var(--txt);
    background:var(--glass2); border:1px solid var(--stroke);
    border-radius:100px; padding:8px 14px;
    -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  }
  .filterbar { display:flex; align-items:center; justify-content:space-between;
               margin-bottom:14px; gap:10px; flex-wrap:wrap; }

  /* Login / first-run setup */
  .gate { max-width:380px; margin:14vh auto 0; padding:30px 26px;
          text-align:center; }
  .gate .dot { width:64px; height:64px; border-radius:20px; margin:0 auto 16px;
    background:linear-gradient(135deg,var(--blue),#5e5ce6);
    display:flex; align-items:center; justify-content:center;
    color:#fff; font-size:34px; }
  .gate h2 { font-size:21px; font-weight:700; letter-spacing:-.02em; }
  .gate p  { font-size:13px; color:var(--dim); margin-top:6px; }
  .gate input {
    width:100%; margin:16px 0 0; padding:15px 18px; font-size:16px;
    font-family:inherit; color:var(--txt);
    background:var(--glass2); border:1px solid var(--stroke);
    border-radius:16px; outline:none;
    -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  }
  .gate input:focus { border-color:var(--blue); }
  .gate .err { color:var(--red); font-size:13px; min-height:18px;
               margin-top:6px; }
  .gate button { width:100%; margin-top:8px; }

  .hidden { display:none !important; }
  .view { display:none; }
  .view.active { display:block; }
  .section { margin-top:12px; padding:20px; }

  /* Bottom tab bar on phones */
  #tabbar { display:none; }
  @media (max-width:760px) {
    aside { display:none; }
    main { padding:10px 10px 92px; }
    #tabbar {
      display:flex; position:fixed; left:10px; right:10px;
      bottom:max(10px, env(safe-area-inset-bottom)); z-index:50;
      border-radius:24px; padding:6px;
    }
    #tabbar button {
      flex:1; display:flex; flex-direction:column; align-items:center; gap:2px;
      border:none; background:none; border-radius:18px; padding:8px 2px;
      font-size:10px; font-weight:600; color:var(--dim); min-height:54px;
    }
    #tabbar button .ic { font-size:20px; }
    #tabbar button.active { background:var(--glass2); color:var(--txt); }
    html { font-size:15px; }
    .grid { grid-template-columns:repeat(2,1fr); }
    .stat { padding:13px 14px; }
    .stat .value { font-size:19px; }
    .topbar { padding:12px 14px; }
    .panel { padding:16px; }
  }
</style>
</head>
<body>

<!-- First-run: create the admin password -->
<div id="setupGate" class="gate glass hidden">
  <div class="dot">&#129302;</div>
  <h2>Welcome to Yoru</h2>
  <p>First-time setup &middot; create the admin password.<br>
     Only the admin can access this console.</p>
  <input id="npw1" type="password" placeholder="New admin password"
         autocomplete="new-password">
  <input id="npw2" type="password" placeholder="Repeat password"
         autocomplete="new-password"
         onkeydown="if(event.key==='Enter')createPassword()">
  <div class="err" id="setupErr"></div>
  <button class="primary" onclick="createPassword()">Create &amp; Sign In</button>
  <p class="note">Stored as a salted hash on the server &mdash; never in a
     config file.</p>
</div>

<div id="login" class="gate glass hidden">
  <div class="dot">&#129302;</div>
  <h2>Yoru Robot</h2>
  <p>Admin console &middot; sign in to continue</p>
  <input id="pw" type="password" placeholder="Admin password" autocomplete="current-password"
         onkeydown="if(event.key==='Enter')login()">
  <div class="err" id="loginErr"></div>
  <button class="primary" onclick="login()">Sign In</button>
  <p class="note">Privacy: this console shows violation metadata only.<br>
     No video is stored or served from here.</p>
</div>

<div id="app" class="hidden">
  <aside class="glass">
    <div class="brand">
      <div class="dot">&#129302;</div>
      <div><h1>Yoru Robot</h1><p>Admin console</p></div>
    </div>
    <button class="navbtn" data-view="setup" onclick="go('setup')">
      <span class="ic">&#128736;</span> Setup</button>
    <button class="navbtn active" data-view="control" onclick="go('control')">
      <span class="ic">&#127918;</span> Control</button>
    <button class="navbtn" data-view="cameras" onclick="go('cameras')">
      <span class="ic">&#128249;</span> Cameras</button>
    <button class="navbtn" data-view="map" onclick="go('map')">
      <span class="ic">&#128506;</span> Map</button>
    <button class="navbtn" data-view="history" onclick="go('history')">
      <span class="ic">&#128203;</span> History</button>
    <div class="spacer"></div>
    <div class="modechip"><span id="modeSide" class="badge b-auto">&mdash;</span></div>
  </aside>

  <main>
    <div class="topbar glass">
      <h2 id="viewTitle">Control</h2>
      <span id="alertChip" class="badge b-alert hidden">&#128680; Smoking detected</span>
      <span id="mode" class="badge b-auto">&mdash;</span>
    </div>

    <!-- ================= SETUP ================= -->
    <div id="view-setup" class="view">
      <div class="row" style="margin-top:0">
        <div class="panel glass">
          <h2>Setup Checklist</h2>
          <div class="steps">
            <div class="step" id="step1"><span class="tick">1</span>
              Drive the robot around to build the map</div>
            <div class="step" id="step2"><span class="tick">2</span>
              Save the map</div>
            <div class="step" id="step3"><span class="tick">3</span>
              Mark each CCTV camera spot on the map</div>
            <div class="step" id="step4"><span class="tick">4</span>
              Restart the robot &mdash; it loads the map and goes on duty</div>
          </div>
          <p class="note" id="setupModeNote">&mdash;</p>
        </div>

        <div class="panel glass">
          <h2>Keyboard Drive (mapping)</h2>
          <div class="keypad">
            <button class="key ghost"></button>
            <button class="key" id="k-w" data-key="w">&#8593;</button>
            <button class="key ghost"></button>
            <button class="key" id="k-a" data-key="a">&#8592;</button>
            <button class="key" id="k-s" data-key="s">&#8595;</button>
            <button class="key" id="k-d" data-key="d">&#8594;</button>
          </div>
          <p class="note" style="text-align:center">
            Click this page once, then drive with <b>W A S D</b> or the
            arrow keys (hold to move). The wireless joystick also works.
            Watch the map grow below, then press Save Map.</p>
          <div class="btnrow">
            <button class="success" onclick="saveMap()">&#128190;&nbsp; Save Map</button>
            <button class="danger" onclick="resetMap()">&#128465;&nbsp; Reset Map (new area)</button>
          </div>
        </div>
      </div>

      <div class="panel glass" style="margin-top:12px">
        <h2>Map &amp; Camera Spots</h2>
        <div class="mapbox" id="mapbox-setup">
          <canvas id="canvas-setup"></canvas>
          <div class="maphint hidden" id="hint-setup"><span>Tap where the robot
            should stand for this camera, then drag towards where it should face
          </span></div>
        </div>
        <div class="maptools">
          <button id="addCamBtn" class="warn" onclick="toggleAddCam()">
            &#128247;&nbsp; Add camera spot</button>
          <button id="addBaseBtn" class="warn" onclick="toggleAddBase()">
            &#8962;&nbsp; Mark base spot</button>
        </div>
        <div class="camlist" id="camlist"></div>
        <p class="note">Mark the spot the robot should drive to when each CCTV
          camera reports smoking &mdash; a point about 1&ndash;2 m in front of where
          people would stand, facing them. Spots apply immediately, no restart
          needed.</p>
        <div class="camlist" id="baselist"></div>
        <p class="note">Mark where the robot should park when Return to Base
          is pressed (or the battery gets low). Applies immediately, no
          restart needed.</p>
      </div>
    </div>

    <!-- ================= CONTROL ================= -->
    <div id="view-control" class="view active">
      <div class="grid">
        <div class="stat glass"><div class="label">Robot activity</div>
          <div class="value small" id="fsm">&mdash;</div></div>
        <div class="stat glass"><div class="label">Active camera</div>
          <div class="value small" id="room">&mdash;</div></div>
        <div class="stat glass"><div class="label">Joystick</div>
          <div class="value small" id="joy">&mdash;</div></div>
        <div class="stat glass"><div class="label">Violations 24 h</div>
          <div class="value" id="v24">&mdash;</div></div>
        <div class="stat glass"><div class="label">Compliance rate</div>
          <div class="value" id="crate">&mdash;</div></div>
      </div>

      <div class="row">
        <div class="panel glass">
          <h2>Robot Control</h2>
          <div class="btnrow">
            <button id="modeBtn" class="primary" onclick="toggleMode()">&mdash;</button>
            <button onclick="testPA()">&#128226;&nbsp; Test Announcement</button>
            <button onclick="goHome()">&#8962;&nbsp; Return to Base</button>
            <button class="danger" onclick="estop()">&#9632;&nbsp; Emergency Stop</button>
          </div>
          <p class="note" id="modeNote">&mdash;</p>
        </div>

        <div class="panel glass">
          <h2>Manual Drive</h2>
          <div class="stickwrap">
            <div id="stick"><div id="knob">&#10021;</div></div>
          </div>
          <p class="note" style="text-align:center">
            Drag to drive &mdash; up/down moves, left/right turns.<br>
            Bluetooth joystick (L2 + stick) always overrides.</p>
        </div>
      </div>
    </div>

    <!-- ================= CAMERAS ================= -->
    <div id="view-cameras" class="view">
      <div class="row" style="margin-top:0">
        <div class="panel glass">
          <h2>CCTV 1 &mdash; built-in webcam</h2>
          <div class="feedbox">
            <img id="feed-cctv0" class="hidden" alt="">
            <div class="nosig" id="nosig-cctv0">Waiting for CCTV frames&hellip;</div>
          </div>
          <p class="note" id="alertNote">No active detection.</p>
        </div>
        <div class="panel glass">
          <h2>CCTV 2 &mdash; USB camera</h2>
          <div class="feedbox">
            <img id="feed-cctv1" class="hidden" alt="">
            <div class="nosig" id="nosig-cctv1">Waiting for CCTV 2 frames&hellip;</div>
          </div>
          <p class="note">Green boxes = persons, red boxes = cigarettes.</p>
        </div>
        <div class="panel glass">
          <h2>Robot onboard camera</h2>
          <div class="feedbox">
            <img id="feed-robot" class="hidden" alt="">
            <div class="nosig" id="nosig-robot">Waiting for robot camera&hellip;</div>
          </div>
          <p class="note">Live view from the robot's Pi camera
            (arrives over Wi-Fi from the robot).</p>
        </div>
      </div>
    </div>

    <!-- ================= MAP ================= -->
    <div id="view-map" class="view">
      <div class="panel glass">
        <h2>Live Map</h2>
        <div class="mapbox" id="mapbox-map">
          <canvas id="canvas-map"></canvas>
          <div class="maphint hidden" id="hint-map"><span>Tap the robot's true position,
            then drag towards where it is facing</span></div>
        </div>
        <div class="maptools">
          <button id="relocBtn" class="warn" onclick="toggleReloc()">
            &#10166;&nbsp; Relocalise</button>
          <button onclick="clearCostmaps()">&#129529;&nbsp; Clear costmaps</button>
        </div>
        <p class="note">Blue arrow = robot. Purple dots = camera spots.
          Red dot = latest violation target. Relocalise tells the localisation
          system where the robot really is (use it when the robot is lost).</p>
      </div>
    </div>

    <!-- ================= HISTORY ================= -->
    <div id="view-history" class="view">
      <div class="section glass" style="margin-top:0">
        <div class="filterbar">
          <h2 style="margin:0">Violation History</h2>
          <select id="roomFilter" onchange="renderTable()">
            <option value="">All cameras</option>
          </select>
        </div>
        <div class="grid" id="roomStats" style="margin-bottom:14px"></div>
        <div class="tablewrap">
          <table>
            <thead><tr><th>Time</th><th>Camera</th><th>Type</th><th>Stage</th>
                       <th>Outcome</th><th>Conf.</th><th>Location</th></tr></thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>
        <p class="note">Metadata-only log (privacy by design). Track IDs are
           anonymous and reset on robot restart.</p>
      </div>
    </div>
  </main>

  <nav id="tabbar" class="glass">
    <button data-view="setup" onclick="go('setup')">
      <span class="ic">&#128736;</span>Setup</button>
    <button class="active" data-view="control" onclick="go('control')">
      <span class="ic">&#127918;</span>Control</button>
    <button data-view="cameras" onclick="go('cameras')">
      <span class="ic">&#128249;</span>Cameras</button>
    <button data-view="map" onclick="go('map')">
      <span class="ic">&#128506;</span>Map</button>
    <button data-view="history" onclick="go('history')">
      <span class="ic">&#128203;</span>History</button>
  </nav>
</div>

<!-- Camera spot naming modal -->
<div id="cammodal">
  <div class="card glass">
    <h3>&#128247; New camera spot</h3>
    <label>Camera</label>
    <select id="camId">
      <option value="cctv1">cctv1 (CCTV camera 1)</option>
      <option value="cctv2">cctv2 (CCTV camera 2)</option>
      <option value="cctv3">cctv3 (CCTV camera 3)</option>
      <option value="cctv4">cctv4 (CCTV camera 4)</option>
    </select>
    <label>Name / location</label>
    <input id="camName" placeholder="e.g. Corridor camera">
    <div class="btns">
      <button onclick="closeCamModal()">Cancel</button>
      <button class="primary" onclick="saveCamSpot()">Save spot</button>
    </div>
  </div>
</div>

<!-- Base spot naming modal -->
<div id="basemodal">
  <div class="card glass">
    <h3>&#8962; New base spot</h3>
    <label>Name</label>
    <input id="baseName" placeholder="e.g. Charging dock">
    <div class="btns">
      <button onclick="closeBaseModal()">Cancel</button>
      <button class="primary" onclick="saveBaseSpot()">Save spot</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
let token = localStorage.getItem('yorutoken') || '';
let incidents = [];
let boot = { needs_setup: false, has_saved_map: false, mapping_active: false };
let cameras = [];
let bases = [];
let lastStatus = null;

function inApp() {
  return !document.getElementById('app').classList.contains('hidden');
}

async function api(path, body) {
  const opts = { headers: { 'X-Auth': token } };
  if (body !== undefined) {
    opts.method = 'POST';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (r.status === 401) {
    // Only bounce to the sign-in screen if we were inside the app -
    // background polls must never replace the first-run setup screen.
    if (inApp()) showLogin();
    throw new Error('auth');
  }
  return r.json();
}

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), 2600);
}

function showLogin() {
  document.getElementById('login').classList.remove('hidden');
  document.getElementById('setupGate').classList.add('hidden');
  document.getElementById('app').classList.add('hidden');
}
function showSetupGate() {
  document.getElementById('setupGate').classList.remove('hidden');
  document.getElementById('login').classList.add('hidden');
  document.getElementById('app').classList.add('hidden');
}
function showApp() {
  document.getElementById('login').classList.add('hidden');
  document.getElementById('setupGate').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
}

async function createPassword() {
  const p1 = document.getElementById('npw1').value;
  const p2 = document.getElementById('npw2').value;
  const err = document.getElementById('setupErr');
  if (p1.length < 4) { err.textContent = 'At least 4 characters.'; return; }
  if (p1 !== p2) { err.textContent = 'Passwords do not match.'; return; }
  const r = await fetch('/api/setup', { method: 'POST',
      body: JSON.stringify({ password: p1 }) });
  const d = await r.json();
  if (r.ok && d.token) {
    token = d.token;
    localStorage.setItem('yorutoken', token);
    showApp(); enterApp(true);
  } else {
    err.textContent = d.error || 'Setup failed.';
  }
}

async function login(pwArg) {
  const pw = pwArg !== undefined ? pwArg : document.getElementById('pw').value;
  const r = await fetch('/api/login', { method:'POST',
      body: JSON.stringify({ password: pw }) });
  if (r.ok) {
    token = (await r.json()).token;
    localStorage.setItem('yorutoken', token);
    showApp(); enterApp(false);
  } else if (r.status === 409) {
    showSetupGate();
  } else {
    document.getElementById('loginErr').textContent = 'Wrong password';
  }
}

function enterApp(firstRun) {
  refresh(); loadIncidents(); loadCameras(); loadBases();
  // Fresh install or no saved map yet -> take the admin to the Setup screen
  if (firstRun || (!boot.has_saved_map)) go('setup');
}

/* ------------- navigation ------------- */
const TITLES = { setup:'Setup', control:'Control', cameras:'Cameras',
                 map:'Live Map', history:'Violation History' };
let activeView = 'control';
function go(view) {
  activeView = view;
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  document.querySelectorAll('[data-view]').forEach(b =>
    b.classList.toggle('active', b.dataset.view === view));
  document.getElementById('viewTitle').textContent = TITLES[view];
  mapVisible = (view === 'map' || view === 'setup');
  if (mapVisible) loadMapInfo(true);
  if (view === 'cameras') startStreams(); else stopStreams();
}

/* ------------- status ------------- */
let paused = false;
async function refresh() {
  try {
    const s = await api('/api/status');
    lastStatus = s;
    paused = s.mode === 'MANUAL';
    for (const id of ['mode', 'modeSide']) {
      const el = document.getElementById(id);
      el.textContent = paused ? 'Admin Control' : 'Autonomous';
      el.className = 'badge ' + (paused ? 'b-manual' : 'b-auto');
    }
    document.getElementById('fsm').textContent = s.fsm_state;
    document.getElementById('room').textContent = s.room;
    const joy = document.getElementById('joy');
    joy.textContent = s.joystick ? 'Connected' : 'Not seen';
    joy.className = 'value small ' + (s.joystick ? 'ok' : 'off');
    document.getElementById('modeBtn').textContent =
      paused ? '▶︎  Resume Autonomy' : '⏸︎  Take Admin Control';
    document.getElementById('modeNote').textContent = paused
      ? 'Robot is under admin control: patrol and escalation are paused. ' +
        'Drive with the joystick or the pad, then resume autonomy.'
      : 'Robot is doing its job: responding to CCTV smoking alerts. ' +
        'Take admin control to drive it manually.';

    // live smoking alert badge + cameras-view note
    const chip = document.getElementById('alertChip');
    const note = document.getElementById('alertNote');
    if (s.alert && s.alert.status) {
      chip.classList.remove('hidden');
      const room = s.alert.room ? ' · ' + s.alert.room : '';
      if (s.alert.status === 'confirmed') {
        chip.className = 'badge b-alert';
        chip.textContent = '🚨 Smoking CONFIRMED' + room;
        note.textContent = `Detection: confirmed` +
          (s.alert.event_class ? ` (${s.alert.event_class})` : '') +
          (s.alert.confidence != null ? ` · confidence ${s.alert.confidence}` : '');
        note.className = 'note bad';
      } else if (s.alert.status === 'possible_vape') {
        chip.className = 'badge b-manual';
        chip.textContent = '💨 Possible vape (unverified)' + room;
        note.textContent = 'Phone-like object held at the mouth — could be a ' +
          'vape. Not escalated: needs the trained vape model to confirm.';
        note.className = 'note';
      } else {
        chip.className = 'badge b-alert';
        chip.textContent = '👀 Checking…' + room;
        note.textContent = `Detection: ${s.alert.status}` +
          (s.alert.event_class ? ` (${s.alert.event_class})` : '') +
          (s.alert.confidence != null ? ` · confidence ${s.alert.confidence}` : '');
        note.className = 'note';
      }
    } else {
      chip.classList.add('hidden');
      note.textContent = 'No active detection.';
      note.className = 'note';
    }

    // setup checklist
    boot.has_saved_map = s.has_saved_map;
    boot.mapping_active = s.mapping_active;
    updateChecklist();
  } catch (e) { /* logged out */ }
}

function updateChecklist() {
  const set = (id, done) =>
    document.getElementById(id).classList.toggle('done', !!done);
  set('step1', boot.mapping_active || boot.has_saved_map);
  set('step2', boot.has_saved_map);
  set('step3', cameras.length > 0);
  set('step4', boot.has_saved_map && !boot.mapping_active && cameras.length > 0);
  document.getElementById('setupModeNote').textContent = boot.mapping_active
    ? 'Mapping mode is ACTIVE - drive slowly and cover every room, ' +
      'then save the map.'
    : (boot.has_saved_map
       ? 'A saved map exists. The robot loads it automatically at startup. ' +
         'You can still re-map: start the robot/sim with mode:=mapping.'
       : 'No map yet. Start the robot (or simulation) - with no saved map it ' +
         'boots straight into mapping mode.');
}

/* ------------- incidents ------------- */
async function loadIncidents() {
  try {
    const d = await api('/api/incidents');
    incidents = d.incidents;
    document.getElementById('v24').textContent = d.stats.last24h;
    document.getElementById('crate').textContent =
        d.stats.total ? d.stats.compliance_rate + '%' : '—';
    const rs = document.getElementById('roomStats');
    rs.innerHTML = '';
    const filt = document.getElementById('roomFilter');
    const current = filt.value;
    filt.innerHTML = '<option value="">All cameras</option>';
    Object.entries(d.stats.per_room).forEach(([room, n]) => {
      rs.innerHTML += `<div class="stat glass"><div class="label">${room}</div>
                       <div class="value">${n}</div></div>`;
      filt.innerHTML += `<option value="${room}">${room}</option>`;
    });
    rs.innerHTML += `<div class="stat glass"><div class="label">total</div>
                     <div class="value">${d.stats.total}</div></div>`;
    filt.value = current;
    renderTable();
  } catch (e) { /* logged out */ }
}

function renderTable() {
  const room = document.getElementById('roomFilter').value;
  const rows = incidents
    .filter(i => !room || (i.room || i.room_id) === room)
    .slice(0, 200)
    .map(i => {
      const t = (i.timestamp || '').replace('T', ' ').slice(0, 19);
      const loc = i.approx_location && i.approx_location.x != null
        ? `(${i.approx_location.x}, ${i.approx_location.y})` : '—';
      const cls = i.outcome === 'complied' ? 'complied'
                : i.outcome === 'logged_no_compliance' ? 'failed' : '';
      return `<tr class="${cls}"><td>${t}</td><td>${i.room || i.room_id || '—'}</td>
        <td>${i.event_class || '—'}</td><td>${i.stage_reached || '—'}</td>
        <td class="outcome">${(i.outcome || '—').replaceAll('_',' ')}</td>
        <td>${i.confidence != null ? i.confidence : '—'}</td><td>${loc}</td></tr>`;
    });
  document.getElementById('tbody').innerHTML =
    rows.join('') || '<tr><td colspan="7">No violations recorded.</td></tr>';
}

async function toggleMode() { await api('/api/mode', { paused: !paused }); refresh(); }
async function testPA() {
  const r = await api('/api/test_pa', {});
  toast(r.note || 'Test announcement sent - you should hear it now');
}
async function goHome()    { await api('/api/home', {}); toast('Returning to base'); }
async function estop()     { await api('/api/stop', {}); refresh();
                             toast('EMERGENCY STOP - autonomy paused'); }

/* ------------- keyboard teleop (Setup view) ------------- */
const held = new Set();
let keyTimer = null;
const KEYMAP = { w:'w', arrowup:'w', s:'s', arrowdown:'s',
                 a:'a', arrowleft:'a', d:'d', arrowright:'d' };

function keysToCmd() {
  let lx = 0, az = 0;
  if (held.has('w')) lx += 1;
  if (held.has('s')) lx -= 1;
  if (held.has('a')) az += 1;
  if (held.has('d')) az -= 1;
  return { lx, az };
}
function paintKeys() {
  for (const k of ['w','a','s','d'])
    document.getElementById('k-' + k).classList.toggle('pressed', held.has(k));
}
function keyLoop() {
  api('/api/drive', keysToCmd()).catch(()=>{});
  if (held.size === 0) { clearInterval(keyTimer); keyTimer = null; }
}
function pressKey(k) {
  if (held.has(k)) return;
  held.add(k); paintKeys();
  api('/api/drive', keysToCmd()).catch(()=>{});
  if (!keyTimer) keyTimer = setInterval(keyLoop, 150);
}
function releaseKey(k) {
  if (!held.delete(k)) return;
  paintKeys();
  api('/api/drive', keysToCmd()).catch(()=>{});
}
window.addEventListener('keydown', e => {
  if (activeView !== 'setup') return;
  if (/input|select|textarea/i.test(e.target.tagName)) return;
  const k = KEYMAP[e.key.toLowerCase()];
  if (!k) return;
  e.preventDefault();
  pressKey(k);
});
window.addEventListener('keyup', e => {
  const k = KEYMAP[e.key.toLowerCase()];
  if (k) releaseKey(k);
});
window.addEventListener('blur', () => { held.forEach(k => releaseKey(k)); });
// on-screen keys work with touch too
for (const k of ['w','a','s','d']) {
  const el = document.getElementById('k-' + k);
  el.addEventListener('pointerdown', e => { e.preventDefault(); pressKey(k); });
  el.addEventListener('pointerup',   () => releaseKey(k));
  el.addEventListener('pointercancel', () => releaseKey(k));
  el.addEventListener('pointerleave', () => releaseKey(k));
}

/* ------------- save map ------------- */
async function saveMap() {
  toast('Saving map…');
  const r = await api('/api/save_map', {});
  if (r.ok) { toast('Map saved ✓  (' + r.path + ')'); boot.has_saved_map = true; }
  else toast(r.error || 'Map save failed');
  updateChecklist();
}

async function resetMap() {
  if (!confirm('Delete the saved map AND all camera spots, and restart ' +
               'the robot into mapping mode? You will need to drive and ' +
               'map the new area, save it, and mark the camera spots again.'))
    return;
  toast('Resetting map…');
  const r = await api('/api/reset_map', {});
  if (r.ok) {
    toast('Map reset ✓ — robot is restarting into mapping mode (~1 min)');
    boot.has_saved_map = false;
    cameras = [];
    renderCamList();
    bases = [];
    renderBaseList();
  } else toast(r.error || 'Map reset failed');
  updateChecklist();
}

/* ------------- camera spots ------------- */
async function loadCameras() {
  try {
    cameras = (await api('/api/cameras')).cameras || [];
    renderCamList();
    updateChecklist();
  } catch (e) { /* logged out */ }
}
function renderCamList() {
  const el = document.getElementById('camlist');
  el.innerHTML = cameras.map((c, i) =>
    `<div class="camrow"><span class="ic">&#128247;</span>
       <span class="nm">${c.name} <span class="xy">(${c.id})</span></span>
       <span class="xy">x ${c.x} · y ${c.y}</span>
       <button onclick="deleteCam(${i})">Delete</button></div>`).join('')
    || '<div class="note">No camera spots marked yet.</div>';
}
async function pushCameras() {
  const r = await api('/api/cameras', { cameras });
  if (r.ok) { cameras = r.cameras; renderCamList(); updateChecklist(); draw(); }
  else toast(r.error || 'Save failed');
}
async function deleteCam(i) {
  const c = cameras[i];
  if (!confirm(`Delete camera spot "${c.name}" (${c.id})?`)) return;
  cameras.splice(i, 1);
  await pushCameras();
  toast('Camera spot deleted');
}

/* ------------- base spot(s) ------------- */
async function loadBases() {
  try {
    bases = (await api('/api/bases')).bases || [];
    renderBaseList();
  } catch (e) { /* logged out */ }
}
function renderBaseList() {
  const el = document.getElementById('baselist');
  el.innerHTML = bases.map((b, i) =>
    `<div class="camrow"><span class="ic">&#8962;</span>
       <span class="nm">${b.name}</span>
       <span class="xy">x ${b.x} · y ${b.y}</span>
       <button onclick="deleteBase(${i})">Delete</button></div>`).join('')
    || '<div class="note">No base spot marked yet.</div>';
}
async function pushBases() {
  const r = await api('/api/bases', { bases });
  if (r.ok) { bases = r.bases; renderBaseList(); draw(); }
  else toast(r.error || 'Save failed');
}
async function deleteBase(i) {
  const b = bases[i];
  if (!confirm(`Delete base spot "${b.name}"?`)) return;
  bases.splice(i, 1);
  await pushBases();
  toast('Base spot deleted');
}

let pendingBaseSpot = null;
function toggleAddBase(forceOff) {
  armMode = (forceOff || armMode === 'addbase') ? null : 'addbase';
  armStart = armDrag = null;
  document.getElementById('addBaseBtn').classList.toggle('on', armMode === 'addbase');
  document.getElementById('hint-setup').classList.toggle('hidden',
                                                          armMode !== 'addbase');
  draw();
}
function openBaseModal(spot) {
  pendingBaseSpot = spot;
  document.getElementById('baseName').value =
    bases.length ? 'Base ' + (bases.length + 1) : 'Base';
  document.getElementById('basemodal').classList.add('show');
}
function closeBaseModal() {
  document.getElementById('basemodal').classList.remove('show');
  pendingBaseSpot = null;
}
async function saveBaseSpot() {
  if (!pendingBaseSpot) return;
  const name = document.getElementById('baseName').value || 'Base';
  const id = 'base' + (bases.length + 1) + '_' + Date.now();
  bases.push({ id, name, x: +pendingBaseSpot.x.toFixed(3),
               y: +pendingBaseSpot.y.toFixed(3),
               yaw: +pendingBaseSpot.yaw.toFixed(3) });
  closeBaseModal();
  await pushBases();
  toast(`Saved base spot "${name}"`);
}

let pendingSpot = null;
function toggleAddCam(forceOff) {
  armMode = (forceOff || armMode === 'addcam') ? null : 'addcam';
  armStart = armDrag = null;
  document.getElementById('addCamBtn').classList.toggle('on', armMode === 'addcam');
  document.getElementById('hint-setup').classList.toggle('hidden',
                                                          armMode !== 'addcam');
  draw();
}
function openCamModal(spot) {
  pendingSpot = spot;
  const used = new Set(cameras.map(c => c.id));
  const sel = document.getElementById('camId');
  for (const opt of sel.options) opt.disabled = used.has(opt.value);
  const free = [...sel.options].find(o => !o.disabled);
  if (free) sel.value = free.value;
  document.getElementById('camName').value =
    'Camera ' + (sel.value.replace('cctv','') || (cameras.length + 1));
  document.getElementById('cammodal').classList.add('show');
}
function closeCamModal() {
  document.getElementById('cammodal').classList.remove('show');
  pendingSpot = null;
}
async function saveCamSpot() {
  if (!pendingSpot) return;
  const id = document.getElementById('camId').value;
  const name = document.getElementById('camName').value || id;
  cameras = cameras.filter(c => c.id !== id);
  cameras.push({ id, name, x: +pendingSpot.x.toFixed(3),
                 y: +pendingSpot.y.toFixed(3),
                 yaw: +pendingSpot.yaw.toFixed(3) });
  closeCamModal();
  await pushCameras();
  toast(`Saved spot for ${id}`);
}

/* ------------- shared map rendering ------------- */
const mapImg = new Image();
let mapVisible = false, mapInfo = null, mapStamp = -1, imgReady = false;
let armMode = null;          // 'reloc' (Map view) | 'addcam' (Setup view)
let armStart = null, armDrag = null;

function activeCanvas() {
  return document.getElementById(
    activeView === 'setup' ? 'canvas-setup' : 'canvas-map');
}
function activeBox() {
  return document.getElementById(
    activeView === 'setup' ? 'mapbox-setup' : 'mapbox-map');
}

function worldToCanvas(canvas, wx, wy) {
  const s = canvas.width / mapImg.width;
  const px = (wx - mapInfo.origin_x) / mapInfo.resolution;
  const py = mapInfo.height - ((wy - mapInfo.origin_y) / mapInfo.resolution);
  return [px * s, py * s];
}
function canvasToWorld(canvas, cx, cy) {
  const s = canvas.width / mapImg.width;
  const wx = (cx / s) * mapInfo.resolution + mapInfo.origin_x;
  const wy = (mapInfo.height - cy / s) * mapInfo.resolution + mapInfo.origin_y;
  return [wx, wy];
}

async function loadMapInfo(force) {
  if (!mapVisible && !force) return;
  try {
    mapInfo = await api('/api/map_info');
    if (mapInfo.cameras) { cameras = mapInfo.cameras; }
    if (!mapInfo.has_map) { drawNoMap(); return; }
    if (mapInfo.stamp !== mapStamp) {
      // <img> cannot send the auth header: fetch the PNG and use a blob URL
      const r = await fetch('/api/map.png?t=' + Date.now(),
                            { headers: { 'X-Auth': token } });
      if (!r.ok) return;
      const url = URL.createObjectURL(await r.blob());
      mapImg.onload = () => {
        imgReady = true;
        URL.revokeObjectURL(url);
        draw();
      };
      mapImg.src = url;
      mapStamp = mapInfo.stamp;
    } else if (imgReady) draw();
  } catch (e) { /* logged out */ }
}

function fitCanvas(canvas, box) {
  const w = box.clientWidth;
  if (!imgReady || !w) return false;
  const h = Math.round(w * mapImg.height / mapImg.width);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w; canvas.height = h;
  }
  return true;
}

function drawNoMap() {
  const canvas = activeCanvas(), box = activeBox();
  canvas.width = box.clientWidth || 600;
  canvas.height = 240;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('color');
  ctx.globalAlpha = 0.5;
  ctx.font = '14px -apple-system, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Waiting for the map (start the robot or simulation)…',
               canvas.width / 2, 120);
  ctx.globalAlpha = 1;
}

function draw() {
  const canvas = activeCanvas(), box = activeBox();
  if (!fitCanvas(canvas, box)) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(mapImg, 0, 0, canvas.width, canvas.height);

  // camera spots (purple, with facing tick + label)
  for (const c of cameras) {
    const [cx, cy] = worldToCanvas(canvas, c.x, c.y);
    ctx.strokeStyle = 'rgba(175,82,222,.95)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + 14 * Math.cos(-c.yaw), cy + 14 * Math.sin(-c.yaw));
    ctx.stroke();
    ctx.fillStyle = 'rgba(175,82,222,.95)';
    ctx.beginPath(); ctx.arc(cx, cy, 6, 0, 7); ctx.fill();
    ctx.font = 'bold 11px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(c.name, cx, cy - 10);
  }

  // base spot(s) (green, with facing tick + label)
  for (const b of bases) {
    const [bx, by] = worldToCanvas(canvas, b.x, b.y);
    ctx.strokeStyle = 'rgba(48,209,88,.95)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(bx, by);
    ctx.lineTo(bx + 14 * Math.cos(-b.yaw), by + 14 * Math.sin(-b.yaw));
    ctx.stroke();
    ctx.fillStyle = 'rgba(48,209,88,.95)';
    ctx.beginPath(); ctx.arc(bx, by, 6, 0, 7); ctx.fill();
    ctx.font = 'bold 11px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(b.name, bx, by - 10);
  }

  if (mapInfo.target) {
    const [tx, ty] = worldToCanvas(canvas, mapInfo.target[0], mapInfo.target[1]);
    ctx.fillStyle = 'rgba(255,69,58,.9)';
    ctx.beginPath(); ctx.arc(tx, ty, 7, 0, 7); ctx.fill();
  }
  if (mapInfo.robot) {
    const [rx, ry] = worldToCanvas(canvas, mapInfo.robot.x, mapInfo.robot.y);
    drawArrow(ctx, rx, ry, -mapInfo.robot.yaw, '#0a84ff');
  }
  if (armStart && armDrag) {
    const ang = Math.atan2(armDrag[1] - armStart[1], armDrag[0] - armStart[0]);
    const color = armMode === 'addcam' ? '#af52de'
                 : armMode === 'addbase' ? '#30d158' : '#ff9f0a';
    drawArrow(ctx, armStart[0], armStart[1], ang, color);
  }
}

function drawArrow(ctx, x, y, ang, color) {
  ctx.save();
  ctx.translate(x, y); ctx.rotate(ang);
  ctx.fillStyle = color;
  ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(13, 0); ctx.lineTo(-8, -8); ctx.lineTo(-4, 0); ctx.lineTo(-8, 8);
  ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.restore();
}

function toggleReloc(forceOff) {
  armMode = (forceOff || armMode === 'reloc') ? null : 'reloc';
  armStart = armDrag = null;
  document.getElementById('relocBtn').classList.toggle('on', armMode === 'reloc');
  document.getElementById('hint-map').classList.toggle('hidden',
                                                       armMode !== 'reloc');
  if (imgReady) draw();
}

function canvasPoint(canvas, e) {
  const r = canvas.getBoundingClientRect();
  return [(e.clientX - r.left) * canvas.width / r.width,
          (e.clientY - r.top) * canvas.height / r.height];
}

for (const cid of ['canvas-map', 'canvas-setup']) {
  const canvas = document.getElementById(cid);
  canvas.addEventListener('pointerdown', e => {
    if (!armMode || !imgReady) return;
    armStart = canvasPoint(canvas, e);
    armDrag = armStart;
    canvas.setPointerCapture(e.pointerId);
    draw();
  });
  canvas.addEventListener('pointermove', e => {
    if (!armMode || !armStart) return;
    armDrag = canvasPoint(canvas, e);
    draw();
  });
  canvas.addEventListener('pointerup', async e => {
    if (!armMode || !armStart) return;
    const end = canvasPoint(canvas, e);
    const [wx, wy] = canvasToWorld(canvas, armStart[0], armStart[1]);
    // canvas y grows downward; world yaw grows counter-clockwise
    const yaw = Math.atan2(-(end[1] - armStart[1]), end[0] - armStart[0]);
    const mode = armMode;
    if (mode === 'reloc') {
      toggleReloc(true);
      const r = await api('/api/relocalise', { x: wx, y: wy, yaw: yaw });
      toast(r.note || `Relocalised to (${wx.toFixed(2)}, ${wy.toFixed(2)})`);
    } else if (mode === 'addbase') {
      toggleAddBase(true);
      openBaseModal({ x: wx, y: wy, yaw: yaw });
    } else {
      toggleAddCam(true);
      openCamModal({ x: wx, y: wy, yaw: yaw });
    }
  });
}

async function clearCostmaps() {
  const r = await api('/api/clear_costmaps', {});
  toast(r.cleared ? `Costmaps cleared (${r.cleared})`
                  : 'Costmap services not available');
}

/* ------------- live camera streams (MJPEG - smooth CCTV video) ------------- */
const FEEDS = ['cctv0', 'cctv1', 'robot'];
let streamsOn = false;
function startStreams() {
  if (streamsOn) return;
  streamsOn = true;
  for (const key of FEEDS) {
    const img = document.getElementById('feed-' + key);
    const nosig = document.getElementById('nosig-' + key);
    img.onload = () => { img.classList.remove('hidden');
                         nosig.classList.add('hidden'); };
    img.onerror = () => { img.classList.add('hidden');
                          nosig.classList.remove('hidden'); };
    // persistent multipart stream: the server pushes every frame as it
    // arrives - no polling, no stutter
    img.src = '/api/stream.mjpg?src=' + key + '&t=' + token;
  }
}
function stopStreams() {
  if (!streamsOn) return;
  streamsOn = false;
  for (const key of FEEDS) {
    const img = document.getElementById('feed-' + key);
    img.onload = img.onerror = null;
    img.removeAttribute('src');   // closes the connection
    img.classList.add('hidden');
    document.getElementById('nosig-' + key).classList.remove('hidden');
  }
}

window.addEventListener('resize', () => { if (imgReady && mapVisible) draw(); });

// Background polls only run once signed in (never on the login/setup screens)
setInterval(() => { if (inApp()) refresh(); }, 2000);
setInterval(() => { if (inApp()) loadIncidents(); }, 5000);
setInterval(() => { if (inApp()) loadMapInfo(false); }, 1000);

/* ------------- boot ------------- */
(async () => {
  try {
    boot = await (await fetch('/api/boot')).json();
  } catch (e) { /* server still starting */ }
  const hashParams = new URLSearchParams(location.hash.slice(1));
  const startView = hashParams.get('view');
  if (startView && TITLES[startView]) go(startView);
  if (boot.needs_setup) {
    showSetupGate();
  } else if (hashParams.get('pw') !== null) {
    login(hashParams.get('pw'));
  } else if (token) {
    showApp(); enterApp(false);
  } else {
    showLogin();
  }
})();
</script>
</body>
</html>
"""
