/*
 * MUVI GO streaming UI scaffold.
 * Add only stream URLs you are authorised to distribute in STREAMS below.
 * Never put provider secrets or payment credentials in this browser file.
 */
function makeChannel(name, category, id, icon) {
 return {
  name, category, id,
  icon: `<span>${icon}</span>`,
  meta: `${category} • FEED NOT CONNECTED`,
  views: "Viewers: —"
 };
}

const channels = [
 makeChannel("ZNBC TV1","News","znbc-tv1","📺"),
 makeChannel("ZNBC TV2","News","znbc-tv2","📺"),
 makeChannel("Diamond TV","News","diamond-tv","📡"),
 makeChannel("Muvi TV","Movies","muvi-tv","🎬"),
 makeChannel("Prime TV","News","prime-tv","📰"),
 makeChannel("KBN TV","News","kbn-tv","🎙️"),
 makeChannel("Sports 24 Zambia","Sports","sports-24","⚽"),
 makeChannel("KidsZone Zambia","Kids","kidszone","🧒"),
 makeChannel("Edu TV Zambia","Education","edu-tv","🎓"),
 makeChannel("MovieMax","Movies","moviemax","🎞️"),
 makeChannel("News 24 Zambia","News","news24","🗞️"),
 makeChannel("Cartoon Kids","Kids","cartoon-kids","🎨"),

 makeChannel("MUVI GO Zambia News","News","mg-zambia-news","📰"),
 makeChannel("MUVI GO Lusaka Headlines","News","mg-lusaka-news","🏙️"),
 makeChannel("MUVI GO Copperbelt Briefing","News","mg-copperbelt-news","⛏️"),
 makeChannel("MUVI GO Business & Markets","News","mg-business-news","📈"),
 makeChannel("MUVI GO Community Reports","News","mg-community-news","🤝"),
 makeChannel("MUVI GO Africa News Desk","News","mg-africa-news","🌍"),
 makeChannel("MUVI GO World News Desk","News","mg-world-news","🌐"),
 makeChannel("MUVI GO Public Affairs","News","mg-public-affairs","🏛️"),

 makeChannel("MUVI GO Zambia Football","Sports","mg-zambia-football","⚽"),
 makeChannel("MUVI GO Local Sports","Sports","mg-local-sports","🏆"),
 makeChannel("MUVI GO African Football","Sports","mg-africa-football","🌍"),
 makeChannel("MUVI GO World Football","Sports","mg-world-football","🥅"),
 makeChannel("MUVI GO Athletics","Sports","mg-athletics","🏃"),
 makeChannel("MUVI GO Basketball","Sports","mg-basketball","🏀"),
 makeChannel("MUVI GO Combat Sports","Sports","mg-combat-sports","🥊"),
 makeChannel("MUVI GO Sports Highlights","Sports","mg-sports-highlights","🎯"),

 makeChannel("MUVI GO Zambian Cinema","Movies","mg-zambian-cinema","🎬"),
 makeChannel("MUVI GO African Cinema","Movies","mg-african-cinema","🌍"),
 makeChannel("MUVI GO Action Movies","Movies","mg-action-movies","💥"),
 makeChannel("MUVI GO Drama Movies","Movies","mg-drama-movies","🎭"),
 makeChannel("MUVI GO Comedy Movies","Movies","mg-comedy-movies","😂"),
 makeChannel("MUVI GO Family Movies","Movies","mg-family-movies","👨‍👩‍👧"),
 makeChannel("MUVI GO Documentary Films","Movies","mg-documentaries","🎥"),
 makeChannel("MUVI GO Classic Cinema","Movies","mg-classic-cinema","🍿"),

 makeChannel("MUVI GO Kids Stories","Kids","mg-kids-stories","📚"),
 makeChannel("MUVI GO Learning Kids","Kids","mg-learning-kids","🧩"),
 makeChannel("MUVI GO Animation Hub","Kids","mg-animation","🎨"),
 makeChannel("MUVI GO Nature for Kids","Kids","mg-kids-nature","🦁"),
 makeChannel("MUVI GO Junior Science","Kids","mg-junior-science","🔬"),
 makeChannel("MUVI GO Kids Music","Kids","mg-kids-music","🎵"),
 makeChannel("MUVI GO Bedtime Stories","Kids","mg-bedtime-stories","🌙"),

 makeChannel("MUVI GO Digital Skills","Education","mg-digital-skills","💻"),
 makeChannel("MUVI GO Science & Technology","Education","mg-science-tech","🔬"),
 makeChannel("MUVI GO Agriculture Learning","Education","mg-agriculture","🌱"),
 makeChannel("MUVI GO Entrepreneurship","Education","mg-entrepreneurship","💼"),
 makeChannel("MUVI GO Health Education","Education","mg-health-education","🩺"),
 makeChannel("MUVI GO Languages & Culture","Education","mg-languages-culture","🗣️"),
 makeChannel("MUVI GO Skills Training","Education","mg-skills-training","🛠️")
];
// Configure authorised HLS feeds here, e.g. "znbc-tv1": "https://your-domain.example/live/znbc-tv1/master.m3u8"
const STREAMS = {"muvi-tv": "/media-files/videos/muvi-test-h264.mp4"};
let category="All", tab="Home", query="", showAll=false, hls=null, currentChannel=null;
const grid=document.getElementById("channelGrid"), count=document.getElementById("channelCount"), toast=document.getElementById("toast");
const video=document.getElementById("liveVideo"), placeholder=document.getElementById("playerPlaceholder"), statusLabel=document.getElementById("playerStatus");
placeholder.classList.add("hidden");
function say(message){toast.textContent=message;toast.classList.add("show");clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>toast.classList.remove("show"),2600)}
function saved(){try{return JSON.parse(localStorage.getItem("muviGoSaved")||"[]")}catch{return []}}
function stopStream(){if(hls){hls.destroy();hls=null}video.pause();video.removeAttribute("src");video.load();placeholder.classList.add("hidden")}
function selectChannel(c){
 currentChannel=c;document.getElementById("nowTitle").textContent=`${c.category} • ${c.name}`;document.getElementById("nowSubtitle").textContent="Zambia • Live TV & On-Demand";
 stopStream();
 statusLabel.textContent="SELECTED: " + c.name.toUpperCase();
 placeholder.innerHTML="";
 const url=STREAMS[c.id];
 if(!url){placeholder.classList.add("hidden");statusLabel.textContent="";document.getElementById("qualityLabel").textContent="";return}
 placeholder.classList.add("hidden");statusLabel.textContent="CONNECTING…";
 if(url.toLowerCase().split("?")[0].endsWith(".mp4")){
   document.getElementById("qualityLabel").textContent="Local MP4 test asset";
   statusLabel.textContent="LOADING TEST VIDEO";
   video.src=url;
   video.load();
   video.play().catch(()=>say("Test video loaded. Press play to begin."));
   document.getElementById("livePanel").scrollIntoView({behavior:"smooth",block:"start"});
   return;
 }
 if(window.Hls&&Hls.isSupported()){
   hls=new Hls({enableWorker:true,lowLatencyMode:true,capLevelToPlayerSize:true,backBufferLength:30});
   hls.loadSource(url);hls.attachMedia(video);
   hls.on(Hls.Events.MANIFEST_PARSED,()=>{statusLabel.textContent="LIVE STREAM";document.getElementById("qualityLabel").textContent="Adaptive bitrate enabled";video.play().catch(()=>say("Press play to begin streaming."))});
   hls.on(Hls.Events.ERROR,(_,data)=>{if(data.fatal){statusLabel.textContent="STREAM ERROR";say("Unable to play this feed. Check the authorised stream URL and server CORS settings.");hls.destroy();hls=null}});
 }else if(video.canPlayType("application/vnd.apple.mpegurl")){
   video.src=url;video.addEventListener("loadedmetadata",()=>{statusLabel.textContent="LIVE STREAM";video.play().catch(()=>{})},{once:true});
 }else{statusLabel.textContent="PLAYER UNSUPPORTED";say("This browser does not support HLS playback. Try a supported modern browser.");}
 document.getElementById("livePanel").scrollIntoView({behavior:"smooth",block:"start"});
}
function render(){
 let items=channels.filter(c=>(category==="All"||c.category===category)&&c.name.toLowerCase().includes(query.toLowerCase()));
 if(tab==="Saved")items=items.filter(c=>saved().includes(c.name));
 if(!showAll&&tab==="Home")items=items.slice(0,12);
 count.textContent=`${items.length} Channel${items.length===1?"":"s"}`;
 grid.innerHTML=items.map(c=>{const configured=Boolean(STREAMS[c.id]);const feedStatus=configured?"FEED CONFIGURED — NOT VERIFIED":"FEED NOT CONNECTED";return `<button class="channel-card" data-id="${c.id}"><span class="saved-mark">${saved().includes(c.name)?"♥":""}</span><div class="logo">${c.icon}</div><h3>${c.name}</h3><div class="views">${c.views}</div></button>`}).join("");
 grid.querySelectorAll(".channel-card").forEach(el=>el.addEventListener("click",e=>{
   const c=channels.find(x=>x.id===el.dataset.id);
   if(e.target.closest(".saved-mark")){let s=saved();s=s.includes(c.name)?s.filter(n=>n!==c.name):[...s,c.name];localStorage.setItem("muviGoSaved",JSON.stringify(s));render();say(s.includes(c.name)?`${c.name} saved.`:`${c.name} removed from Saved.`);return}
   selectChannel(c);
 }));
}

/* MUVI GO Profile integration v1 */
(() => {
  const byId = id => document.getElementById(id);
  const panel = byId("profilePanel");
  const status = byId("profileStatus");
  const signedOut = byId("profileSignedOut");
  const signedIn = byId("profileSignedIn");
  let profileUser = null;

  function setStatus(message) {
    if (status) status.textContent = message;
  }

  function showProfile() {
    const authenticated = Boolean(profileUser);
    signedOut.classList.toggle("hidden", authenticated);
    signedIn.classList.toggle("hidden", !authenticated);

    if (authenticated) {
      byId("profileUserName").textContent = profileUser.name || "Account";
      byId("profileUserEmail").textContent = profileUser.email || "";
      byId("profileUserRole").textContent = profileUser.role || "viewer";
    }
  }

  function updateProfileVisibility() {
    const visible = typeof tab !== "undefined" && tab === "Profile";
    if (panel) panel.classList.toggle("hidden", !visible);

    ["livePanel", "channelGrid", "mediaLibrary"].forEach(id => {
      const element = byId(id);
      if (element) element.classList.toggle("hidden", visible);
    });

    document.querySelectorAll("main > .section-heading, main > .filters")
      .forEach(element => element.classList.toggle("hidden", visible));
  }

  async function request(url, method, payload) {
    const options = {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Accept": "application/json" }
    };

    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }

    const response = await fetch(url, options);
    let data;
    try {
      data = await response.json();
    } catch (_) {
      throw new Error("The server returned an unreadable response.");
    }

    if (!response.ok || !data || data.ok !== true) {
      const messages = {
        invalid_credentials: "Email or password is incorrect.",
        email_password_required: "Enter your email and password.",
        name_email_password_required: "Complete all registration fields.",
        invalid_name: "Enter a name of up to 80 characters.",
        invalid_email: "Enter a valid email address.",
        password_length_invalid: "Password must be 10–256 characters.",
        account_already_exists: "An account with that email already exists."
      };
      throw new Error(
        messages[data && data.error] ||
        "Request failed (" + response.status + "). Please try again."
      );
    }
    return data;
  }

  async function refreshProfile() {
    try {
      const data = await request("/api/auth/me", "GET");
      profileUser = data.authenticated ? data.user : null;
      showProfile();
      setStatus(profileUser
        ? "Signed in successfully."
        : "Sign in or create an account to access your profile.");
    } catch (_) {
      profileUser = null;
      showProfile();
      setStatus("Could not check your session. Check the server and retry.");
    }
  }

  async function handleForm(formId, endpoint, getPayload) {
    const form = byId(formId);
    if (!form) return;

    form.addEventListener("submit", async event => {
      event.preventDefault();
      const submit = form.querySelector('button[type="submit"]');
      if (submit) submit.disabled = true;
      setStatus("Please wait…");

      try {
        const data = await request(endpoint, "POST", getPayload(form));
        profileUser = data.user || null;
        form.reset();
        showProfile();
        setStatus(profileUser
          ? "Welcome, " + (profileUser.name || "viewer") + "."
          : "Request completed.");

        // Route authenticated accounts to their correct dashboard.
        if (endpoint === "/api/auth/login" && profileUser) {
          window.location.assign(
            profileUser.role === "admin" ? "/admin" : "/account"
          );
        }
      } catch (error) {
        setStatus(error.message || "Unable to complete the request.");
      } finally {
        if (submit) submit.disabled = false;
      }
    });
  }

  handleForm("profileLoginForm", "/api/auth/login", form => ({
    email: byId("profileLoginEmail").value.trim(),
    password: byId("profileLoginPassword").value
  }));

  handleForm("profileRegisterForm", "/api/auth/register", form => ({
    name: byId("profileRegisterName").value.trim(),
    email: byId("profileRegisterEmail").value.trim(),
    password: byId("profileRegisterPassword").value
  }));

  byId("profileLogout").addEventListener("click", async () => {
    const button = byId("profileLogout");
    button.disabled = true;
    setStatus("Signing out…");
    try {
      await request("/api/auth/logout", "POST", {});
      profileUser = null;
      showProfile();
      setStatus("You have signed out.");
    } catch (error) {
      setStatus(error.message || "Could not sign out. Please retry.");
    } finally {
      button.disabled = false;
    }
  });

  window.muviGoRefreshProfile = refreshProfile;
  window.muviGoUpdateProfileVisibility = updateProfileVisibility;

  showProfile();
  refreshProfile();
  updateProfileVisibility();
})();

document.querySelectorAll(".filter").forEach(b=>b.addEventListener("click",()=>{category=b.dataset.category;tab="Channels";document.querySelectorAll(".filter").forEach(x=>x.classList.toggle("active",x===b));document.querySelectorAll(".nav-item").forEach(x=>x.classList.toggle("selected",x.dataset.tab==="Channels"));window.muviGoUpdateProfileVisibility();render()}));
document.querySelectorAll(".nav-item").forEach(b=>b.addEventListener("click",()=>{tab=b.dataset.tab;document.querySelectorAll(".nav-item").forEach(x=>x.classList.toggle("selected",x===b));if(tab==="Saved"){category="All";showAll=true;say("Saved channels are stored on this device.");}else if(tab==="Profile"){window.muviGoUpdateProfileVisibility(); window.muviGoRefreshProfile();}else if(tab==="Live"){say("Choose a channel. Only configured authorised feeds can play.");}else if(tab==="Home"){category="All";showAll=false;query="";}else if(tab==="Channels"){showAll=true;}window.muviGoUpdateProfileVisibility();render()}));
document.getElementById("searchToggle").addEventListener("click",()=>{document.getElementById("searchPanel").classList.toggle("hidden");if(!document.getElementById("searchPanel").classList.contains("hidden"))document.getElementById("searchInput").focus()});
document.getElementById("searchInput").addEventListener("input",e=>{query=e.target.value;showAll=true;render()});
document.getElementById("notify").addEventListener("click",()=>say("Notifications will appear when the account service is connected."));
document.getElementById("viewAll").addEventListener("click",()=>{showAll=!showAll;document.getElementById("viewAll").innerHTML=showAll?'Show less <span>☷</span>':'See all <span>☷</span>';render()});
document.getElementById("pictureBtn").addEventListener("click",()=>say("Picture-in-picture support depends on browser and device."));
document.getElementById("fullscreenBtn").addEventListener("click",()=>{const el=document.querySelector(".video-stage");if(el.requestFullscreen)el.requestFullscreen().catch(()=>say("Full screen is not available in this browser."));else say("Full screen is not supported in this browser.")});
video.addEventListener("playing",()=>{
 placeholder.classList.add("hidden");
 statusLabel.textContent=video.currentSrc.toLowerCase().split("?")[0].endsWith(".mp4")?"TEST VIDEO PLAYING":"LIVE STREAM";
});

// MUVI GO playback events: report only for the currently selected,
// configured channel. Unconfigured channels retain their no-feed status.
function hasConfiguredSelection(){
 return Boolean(currentChannel && STREAMS[currentChannel.id]);
}

video.addEventListener("canplay",()=>{
 if(hasConfiguredSelection()) statusLabel.textContent="READY TO PLAY";
});

video.addEventListener("waiting",()=>{
 if(hasConfiguredSelection()) statusLabel.textContent="BUFFERING…";
});

video.addEventListener("pause",()=>{
 if(hasConfiguredSelection() && !video.ended && video.currentSrc){
   statusLabel.textContent="PAUSED";
 }
});

video.addEventListener("ended",()=>{
 if(hasConfiguredSelection()){
   statusLabel.textContent=video.currentSrc.toLowerCase().split("?")[0].endsWith(".mp4")
     ?"TEST VIDEO ENDED":"STREAM ENDED";
 }
});

video.addEventListener("error",()=>{
 if(hasConfiguredSelection() && video.error){
   statusLabel.textContent="PLAYBACK ERROR";
   say("Video playback failed. Check the media file and browser playback support.");
 }
});
render();
if("serviceWorker" in navigator)window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js").catch(()=>{}));


/* MUVI GO on-demand library: uses only files returned by /api/library. */
(() => {
  const status = document.getElementById("mediaLibraryStatus");
  const videoList = document.getElementById("videoLibrary");
  const musicList = document.getElementById("musicLibrary");
  const videoPlayer = document.getElementById("libraryVideo");
  const audioPlayer = document.getElementById("libraryAudio");
  const refreshButton = document.getElementById("refreshMedia");

  if (!status || !videoList || !musicList || !videoPlayer || !audioPlayer) return;

  function showEmpty(container, message) {
    const empty = document.createElement("div");
    empty.className = "media-empty";
    empty.textContent = message;
    container.replaceChildren(empty);
  }

  function makeMediaButton(item, kind) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "media-item";

    const title = document.createElement("strong");
    title.textContent = item.title || item.filename || "Untitled media";

    const detail = document.createElement("span");
    detail.textContent = kind === "video" ? "▶ Play video" : "♫ Play song";

    button.append(title, detail);
    button.addEventListener("click", async () => {
      const player = kind === "video" ? videoPlayer : audioPlayer;
      const other = kind === "video" ? audioPlayer : videoPlayer;

      other.pause();
      player.pause();
      player.src = item.url;
      player.load();

      try {
        await player.play();
        status.textContent = "Now playing: " + (item.title || item.filename);
      } catch (error) {
        status.textContent =
          "Media selected. Press Play in the player if playback did not start.";
      }
    });
    return button;
  }

  async function loadLibrary() {
    status.textContent = "Loading your media library…";
    if (refreshButton) refreshButton.disabled = true;

    try {
      const response = await fetch("/api/library", { cache: "no-store" });
      if (!response.ok) throw new Error("Library request failed: " + response.status);

      const items = await response.json();
      if (!Array.isArray(items)) throw new Error("Unexpected library response");

      const videos = items.filter(item =>
        item && item.type === "video" &&
        typeof item.url === "string" && item.url.startsWith("/media-files/videos/")
      );
      const songs = items.filter(item =>
        item && item.type === "music" &&
        typeof item.url === "string" && item.url.startsWith("/media-files/music/")
      );

      videoList.replaceChildren();
      musicList.replaceChildren();

      videos.forEach(item => videoList.appendChild(makeMediaButton(item, "video")));
      songs.forEach(item => musicList.appendChild(makeMediaButton(item, "music")));

      if (!videos.length) showEmpty(videoList, "No videos added yet.");
      if (!songs.length) showEmpty(musicList, "No songs added yet. Add audio files to media/music.");

      status.textContent =
        "Library loaded: " + videos.length + " video(s) and " +
        songs.length + " song(s).";
    } catch (error) {
      status.textContent = "Could not load the media library. Check the server and tap Refresh.";
      showEmpty(videoList, "Video list unavailable.");
      showEmpty(musicList, "Music list unavailable.");
    } finally {
      if (refreshButton) refreshButton.disabled = false;
    }
  }

  if (refreshButton) refreshButton.addEventListener("click", loadLibrary);
  loadLibrary();
})();


/* MUVI_GO_HIDE_CHANNEL_FEED_CAPTIONS_V1 */
(function () {
  const hiddenLabels =
    /^(?:FEED NOT CONNECTED|CONFIGURED\s*[—–-]\s*NOT VERIFIED)$/i;

  function hideChannelCaptions() {
    document.querySelectorAll("*").forEach(function (el) {
      const label = (el.textContent || "").replace(/\s+/g, " ").trim();

      if (!hiddenLabels.test(label)) return;

      const childAlreadyMatches = Array.from(el.children).some(function (child) {
        return hiddenLabels.test(
          (child.textContent || "").replace(/\s+/g, " ").trim()
        );
      });

      if (!childAlreadyMatches) {
        el.style.setProperty("display", "none", "important");
      }
    });
  }

  hideChannelCaptions();

  const observer = new MutationObserver(hideChannelCaptions);
  observer.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true
  });
})();
