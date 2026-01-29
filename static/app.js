const socket = io();

const brightness = document.getElementById("brightness");
const brightnessVal = document.getElementById("brightness-val");
const contrast = document.getElementById("contrast");
const contrastVal = document.getElementById("contrast-val");
const rescan = document.getElementById("rescan");
const ddcStatus = document.getElementById("ddc-status");
const upload = document.getElementById("upload");
const imageList = document.getElementById("image-list");
const mode = document.getElementById("mode");
const scale = document.getElementById("scale");
const scaleVal = document.getElementById("scale-val");

let state = null;
let ddcSupports = { brightness: true, contrast: true };

function debounce(fn, wait) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

const sendDdc = debounce((payload) => socket.emit("ddc.set", payload), 50);

brightness.addEventListener("input", (e) => {
  brightnessVal.textContent = e.target.value;
  sendDdc({ brightness: Number(e.target.value) });
});

contrast.addEventListener("input", (e) => {
  contrastVal.textContent = e.target.value;
  sendDdc({ contrast: Number(e.target.value) });
});

rescan.addEventListener("click", async () => {
  await fetch("/api/ddc/rescan", { method: "POST" });
});

mode.addEventListener("change", () => {
  socket.emit("render.patch", { transform: { ...state.render.transform, mode: mode.value } });
});

scale.addEventListener("input", (e) => {
  scaleVal.textContent = Number(e.target.value).toFixed(1);
  socket.emit("render.patch", { transform: { ...state.render.transform, scale: Number(e.target.value) } });
});

upload.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  await fetch("/api/images", { method: "POST", body: form });
  await refreshImages();
});

async function refreshImages() {
  const res = await fetch("/api/images");
  const images = await res.json();
  imageList.innerHTML = "";
  images.forEach((img) => {
    const div = document.createElement("div");
    div.className = "image-item";
    div.innerHTML = `<img src="/api/images/${img.id}/thumb" /><div>${img.original_name}</div>`;
    div.addEventListener("click", () => {
      socket.emit("image.select", { imageId: img.id });
    });
    imageList.appendChild(div);
  });
}

socket.on("state.snapshot", (payload) => {
  state = payload.state;
  if (!state) return;
  const ddc = state.ddc;
  ddcSupports = ddc.supported || ddcSupports;
  brightness.disabled = !ddcSupports.brightness;
  contrast.disabled = !ddcSupports.contrast;
  brightness.value = ddc.values?.brightness?.cur ?? brightness.value;
  contrast.value = ddc.values?.contrast?.cur ?? contrast.value;
  brightness.max = ddc.values?.brightness?.max ?? 100;
  contrast.max = ddc.values?.contrast?.max ?? 100;
  brightnessVal.textContent = brightness.value;
  contrastVal.textContent = contrast.value;
  ddcStatus.textContent = `DDC: ${ddc.status} ${ddc.lastError ? "(" + ddc.lastError + ")" : ""}`;
  mode.value = state.render.transform.mode;
  scale.value = state.render.transform.scale;
  scaleVal.textContent = Number(scale.value).toFixed(1);
});

socket.on("connect", () => {
  refreshImages();
});

socket.on("ddc.updated", (payload) => {
  const values = payload.values;
  if (values?.brightness?.cur !== undefined) brightness.value = values.brightness.cur;
  if (values?.contrast?.cur !== undefined) contrast.value = values.contrast.cur;
  brightnessVal.textContent = brightness.value;
  contrastVal.textContent = contrast.value;
});
