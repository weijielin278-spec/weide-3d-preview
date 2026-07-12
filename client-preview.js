import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/controls/OrbitControls.js";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";
import { STLExporter } from "./vendor/three/exporters/STLExporter.js";

const state = {
  user: null,
  imageDataUrl: "",
  fileName: "",
  generating: false,
  autoRotate: false,
  materialMode: "glass",
};

const $ = (selector) => document.querySelector(selector);

const canvas = $("#clientViewer");
const emptyState = $("#clientViewerEmpty");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101216);

const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 2000);
camera.position.set(0, -18, 230);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.enableRotate = true;
controls.enablePan = true;
controls.enableZoom = true;
controls.minDistance = 45;
controls.maxDistance = 420;
controls.target.set(0, 0, 0);

const grid = new THREE.GridHelper(240, 24, 0x5a6068, 0x2a2e34);
grid.rotation.x = Math.PI / 2;
grid.position.z = -18;
scene.add(grid);

const modelGroup = new THREE.Group();
let currentModel = null;
let fallbackColorTexture = null;
scene.add(modelGroup);
scene.add(new THREE.HemisphereLight(0xffffff, 0xd7c7b6, 2.4));

const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
keyLight.position.set(-80, -120, 160);
scene.add(keyLight);

const warmLight = new THREE.DirectionalLight(0xf0c865, 1.1);
warmLight.position.set(120, 80, 100);
scene.add(warmLight);

async function init() {
  await refreshUser();
  bindEvents();
  resize();
  await loadLocalDemoModel();
  animate();
}

async function loadLocalDemoModel() {
  const demoModel = new URLSearchParams(location.search).get("demoModel");
  if (!demoModel || !["127.0.0.1", "localhost"].includes(location.hostname)) return;
  try {
    await loadModel(demoModel);
    $("#clientModelTitle").textContent = "3D Preview Ready";
    $("#clientModelMeta").textContent = "Loaded from local test cache";
    setStatus("Local test model loaded. You can test Download STL now.");
  } catch (error) {
    setStatus(`Local test model failed to load: ${error.message}`);
  }
}

async function refreshUser() {
  const response = await fetch("/api/me");
  const result = await response.json();
  if (!result.user) {
    location.href = "./login.html?next=client-preview.html";
    return;
  }
  state.user = result.user;
  renderUser();
}

function renderUser() {
  $("#clientEmail").textContent = state.user?.email || "";
  $("#clientCredits").textContent = `${state.user?.credits ?? 0} credits left`;
}

function bindEvents() {
  $("#clientFile").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    await readImage(file);
  });
  $("#clientGenerateBtn").addEventListener("click", generatePreview);
  document.querySelectorAll(".client-view").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  document.querySelectorAll(".client-material").forEach((button) => {
    button.addEventListener("click", () => setMaterialMode(button.dataset.material));
  });
  $("#clientStlBtn")?.addEventListener("click", exportSTL);
  $("#clientContactToggle")?.addEventListener("click", toggleContactList);
  window.addEventListener("resize", resize);
}

function toggleContactList() {
  const list = $("#clientContactList");
  const button = $("#clientContactToggle");
  if (!list || !button) return;
  const willOpen = list.hidden;
  list.hidden = !willOpen;
  button.textContent = willOpen ? "Hide Contact Info" : "Contact Us";
}

function readImage(file) {
  if (!file.type.startsWith("image/")) {
    setStatus("Please choose a PNG, JPG, or WEBP image.");
    return Promise.resolve();
  }

  state.fileName = file.name;
  $("#clientFileName").textContent = file.name;
  setStatus("Reading image...");

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      state.imageDataUrl = String(reader.result || "");
      const preview = $("#clientImagePreview");
      preview.src = state.imageDataUrl;
      preview.hidden = false;
      loadFallbackColorTexture(state.imageDataUrl);
      $("#clientModelTitle").textContent = "Artwork Uploaded";
      $("#clientModelMeta").textContent = "Click Generate 3D Preview";
      setEmptyState("Artwork uploaded. Start the 3D preview to load your model here.");
      setStatus("Image uploaded. You can now generate a 3D preview.");
      resolve();
    };
    reader.onerror = () => {
      setStatus("Image read failed. Please try another file.");
      reject(new Error("Image read failed"));
    };
    reader.readAsDataURL(file);
  });
}

async function generatePreview() {
  if (state.generating) return;
  if (!state.imageDataUrl) {
    setStatus("Please upload artwork first.");
    return;
  }

  state.generating = true;
  const button = $("#clientGenerateBtn");
  button.disabled = true;
  button.textContent = "Generating...";
  clearModel();
  setEmptyState("Generating your 3D preview. Please keep this page open.");
  setStatus("Generating your 3D preview. This may take a few minutes.");
  $("#clientModelTitle").textContent = "Generating 3D Preview";
  $("#clientModelMeta").textContent = "The model will load automatically when ready";

  try {
    const response = await fetch("/api/generate-3d", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        imageDataUrl: state.imageDataUrl,
        fileName: state.fileName,
        material: "client_glass_ornament_preview",
        sizeMode: "default",
        dimensions: null,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(formatError(result.error || "Generation failed"));
    if (result.user) {
      state.user = result.user;
      renderUser();
    }
    await loadModel(result.glbUrl);
    $("#clientModelTitle").textContent = "3D Preview Ready";
    $("#clientModelMeta").textContent = result.fromCache ? "Loaded from cache. No credits used." : `${result.creditsUsed || 20} credits used`;
    setStatus(result.fromCache ? "Loaded from local cache. No credits were used." : "3D preview is ready. Drag to rotate and scroll to zoom.");
  } catch (error) {
    $("#clientModelTitle").textContent = "Generation Failed";
    $("#clientModelMeta").textContent = "Please check your image or try again later";
    setEmptyState("Generation failed. Please try another image or try again later.");
    setStatus(`Generation failed: ${formatError(error.message)}`);
  } finally {
    button.disabled = false;
    button.textContent = "Generate 3D Preview";
    state.generating = false;
  }
}

function formatError(message = "") {
  const text = String(message);
  if (/credits|insufficient funds|balance/i.test(text)) return "Not enough credits. Please contact us to add credits.";
  if (/login|sign in|unauthorized/i.test(text)) return "Please sign in first.";
  return text || "Generation failed";
}

async function loadModel(url) {
  const loadUrl = url.startsWith("http") ? `/api/model?url=${encodeURIComponent(url)}` : url;
  const gltf = await new GLTFLoader().loadAsync(loadUrl);
  clearModel();
  const root = gltf.scene;
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  root.position.sub(center);
  const maxAxis = Math.max(size.x, size.y, size.z, 1);
  root.scale.setScalar(90 / maxAxis);
  currentModel = root;
  currentModel.traverse((child) => {
    if (!child.isMesh) return;
    child.userData.colorPreviewMaterial = child.material?.clone ? child.material.clone() : child.material;
  });
  applyMaterialMode();
  modelGroup.add(root);
  setEmptyState("", true);
  controls.target.set(0, 0, 0);
  controls.update();
}

function clearModel() {
  modelGroup.clear();
  currentModel = null;
}

function setStatus(message) {
  $("#clientStatus").textContent = message;
}

function setEmptyState(message, hidden = false) {
  if (!emptyState) return;
  emptyState.hidden = hidden;
  if (!hidden) {
    emptyState.querySelector("span").textContent = message;
  }
}

function setMaterialMode(mode) {
  state.materialMode = mode === "color" ? "color" : "glass";
  document.querySelectorAll(".client-material").forEach((button) => {
    button.classList.toggle("active", button.dataset.material === state.materialMode);
  });
  applyMaterialMode();
}

function applyMaterialMode() {
  if (!currentModel) return;
  const glassMaterial = new THREE.MeshPhysicalMaterial({
    color: 0xeaf7ff,
    roughness: 0.08,
    metalness: 0,
    transmission: 0.72,
    transparent: true,
    opacity: 0.56,
    thickness: 3.2,
    ior: 1.46,
    clearcoat: 1,
    clearcoatRoughness: 0.05,
  });
  currentModel.traverse((child) => {
    if (!child.isMesh) return;
    child.material = state.materialMode === "color" ? colorPreviewMaterial(child) : glassMaterial;
    child.material.needsUpdate = true;
  });
}

function colorPreviewMaterial(mesh) {
  const original = mesh.userData.colorPreviewMaterial;
  if (Array.isArray(original)) return original.map((item) => (item?.clone ? item.clone() : item));
  if (original?.map) return original.clone ? original.clone() : original;
  if (fallbackColorTexture) {
    return new THREE.MeshStandardMaterial({
      map: fallbackColorTexture,
      roughness: 0.42,
      metalness: 0.02,
    });
  }
  return new THREE.MeshStandardMaterial({
    color: 0xf4d064,
    roughness: 0.45,
    metalness: 0.02,
  });
}

function loadFallbackColorTexture(dataUrl) {
  new THREE.TextureLoader().load(
    dataUrl,
    (texture) => {
      texture.colorSpace = THREE.SRGBColorSpace;
      fallbackColorTexture = texture;
      if (state.materialMode === "color") applyMaterialMode();
    },
    undefined,
    () => {
      fallbackColorTexture = null;
    },
  );
}

function exportSTL() {
  if (!currentModel || modelGroup.children.length === 0) {
    setStatus("Please generate a 3D preview before downloading STL.");
    return;
  }
  try {
    const exporter = new STLExporter();
    const result = exporter.parse(modelGroup, { binary: true });
    const safeName = (state.fileName || "custom-ornament").replace(/\.[^.]+$/, "").replace(/[^a-z0-9_-]+/gi, "-").slice(0, 48);
    const fileName = `${safeName || "custom-ornament"}-${Date.now()}.stl`;
    downloadBlob(new Blob([result], { type: "model/stl" }), fileName);
    setStatus(`STL downloaded: ${fileName}`);
  } catch (error) {
    setStatus(`STL export failed: ${error.message}`);
  }
}

function downloadBlob(blob, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function setView(view) {
  document.querySelectorAll(".client-view").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  state.autoRotate = view === "auto";
  const distance = 210;
  if (view === "front") camera.position.set(0, -18, 230);
  if (view === "left") camera.position.set(-distance, -10, 64);
  if (view === "top") camera.position.set(0, -distance, 160);
  controls.target.set(0, 0, 0);
  controls.update();
}

function resize() {
  const rect = canvas.parentElement.getBoundingClientRect();
  const width = Math.max(320, rect.width);
  const height = Math.max(320, rect.height);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function animate() {
  requestAnimationFrame(animate);
  if (state.autoRotate) modelGroup.rotation.y += 0.008;
  controls.update();
  renderer.render(scene, camera);
}

init();
