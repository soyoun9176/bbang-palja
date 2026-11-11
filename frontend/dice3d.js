let threePromise;
const skins = {
  walkin: { id: 'walkin', face: '#f8e8c8', trim: '#efb6a8', pip: '#38243f', glint: '#fff8e8' },
  plain: { id: 'plain', face: '#fff0d5', trim: '#e5b85c', pip: '#39271f', glint: '#fff8e7' },
  rainbow: { id: 'rainbow', face: '#e4d7ed', trim: '#f3a8d4', pip: '#30203f', glint: '#fff5ce' },
  silver: { id: 'silver', face: '#d8d2e3', trim: '#f1e0cf', pip: '#30263d', glint: '#fff8f0' },
  gold: { id: 'gold', face: '#f4b4d0', trim: '#ffe18e', pip: '#513951', glint: '#fff2d2' },
  pink: { id: 'pink', face: '#dfb4df', trim: '#ffe58f', pip: '#392746', glint: '#fff4e1' },
};
const pipPositions = {
  1: [[1, 1]], 2: [[0, 0], [2, 2]], 3: [[0, 0], [1, 1], [2, 2]],
  4: [[0, 0], [2, 0], [0, 2], [2, 2]], 5: [[0, 0], [2, 0], [1, 1], [0, 2], [2, 2]],
  6: [[0, 0], [2, 0], [0, 1], [2, 1], [0, 2], [2, 2]],
};

function loadThree() {
  if (!threePromise) threePromise = Promise.all([
    import('https://esm.sh/three@0.180.0'),
    import('https://esm.sh/three@0.180.0/examples/jsm/geometries/RoundedBoxGeometry.js'),
  ]).then(([THREE, geometry]) => ({ THREE, RoundedBoxGeometry: geometry.RoundedBoxGeometry }));
  return threePromise;
}

function faceTexture(THREE, value, skin, isResult = false) {
  const source = document.createElement('canvas');
  source.width = source.height = 64;
  const ctx = source.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = skin.face;
  ctx.fillRect(0, 0, 64, 64);
  // Chunky pixel highlights and a restrained, evenly repeated corner motif.
  ctx.fillStyle = skin.glint;
  ctx.fillRect(8, 8, 12, 3); ctx.fillRect(8, 8, 3, 12);
  ctx.fillStyle = skin.trim;
  [[8, 8, 8, 2], [8, 8, 2, 8], [48, 8, 8, 2], [54, 8, 2, 8],
    [8, 54, 8, 2], [8, 48, 2, 8], [48, 54, 8, 2], [54, 48, 2, 8]]
    .forEach(([x, y, w, h]) => ctx.fillRect(x, y, w, h));
  if (skin.id === 'rainbow') {
    const blocks = ['#f29cce', '#ffe19b', '#8fd9ca', '#8fc9ef', '#c3a5e8'];
    for (let row = 0; row < 5; row++) for (let col = 0; col < 5; col++) {
      ctx.fillStyle = blocks[(row + col) % blocks.length];
      ctx.globalAlpha = 0.38;
      ctx.fillRect(13 + col * 8, 13 + row * 8, 6, 6);
    }
    ctx.globalAlpha = 1;
  }
  if (skin.id === 'silver') {
    ctx.fillStyle = '#fff8';
    for (let i = 0; i < 5; i++) {
      ctx.fillRect(12 + i * 3, 19 + i * 4, 4, 2); ctx.fillRect(48 - i * 3, 19 + i * 4, 4, 2);
      ctx.fillRect(12 + i * 3, 45 - i * 4, 4, 2); ctx.fillRect(48 - i * 3, 45 - i * 4, 4, 2);
    }
  }
  if (skin.id === 'walkin') {
    ctx.fillStyle = '#f4a7ba'; ctx.fillRect(15, 15, 4, 4); ctx.fillRect(19, 19, 4, 4); ctx.fillRect(23, 15, 4, 4); ctx.fillRect(19, 23, 4, 4);
    ctx.fillRect(39, 39, 4, 4); ctx.fillRect(43, 43, 4, 4); ctx.fillRect(47, 39, 4, 4); ctx.fillRect(43, 47, 4, 4);
  }
  // The pip is deliberately flat, large, and high contrast so it stays clear at phone size.
  if (value === 'milk') {
    ctx.fillStyle = '#fff8e8'; ctx.fillRect(18, 12, 28, 40);
    ctx.fillStyle = skin.trim; ctx.fillRect(18, 23, 28, 10);
    ctx.fillStyle = skin.pip; ctx.font = 'bold 10px sans-serif'; ctx.textAlign = 'center';
    ctx.textBaseline = 'middle'; ctx.fillText('우유', 32, 40);
  } else if (Number(value) >= 7) {
    ctx.fillStyle = skin.pip; ctx.font = 'bold 26px monospace'; ctx.textAlign = 'center';
    ctx.textBaseline = 'middle'; ctx.fillText(String(value), 32, 33);
    ctx.fillStyle = skin.glint; ctx.fillRect(19, 47, 26, 2);
  } else {
    const spots = pipPositions[Number(value)] || pipPositions[1];
    for (const [col, row] of spots) {
      const x = 19 + col * 13, y = 19 + row * 13;
      ctx.fillStyle = skin.pip;
      ctx.fillRect(x, y, 8, 8);
      ctx.fillStyle = skin.pip;
      ctx.fillRect(x + 2, y - 2, 4, 12); ctx.fillRect(x - 2, y + 2, 12, 4);
      ctx.fillStyle = skin.glint;
      ctx.fillRect(x + 1, y + 1, 2, 2);
    }
  }
  if (isResult) {
    ctx.fillStyle = skin.trim;
    ctx.fillRect(28, 4, 8, 3); ctx.fillRect(28, 57, 8, 3);
  }
  const pixel = document.createElement('canvas'); pixel.width = pixel.height = 64;
  pixel.getContext('2d').drawImage(source, 0, 0);
  const map = new THREE.CanvasTexture(pixel);
  map.colorSpace = THREE.SRGBColorSpace;
  map.magFilter = THREE.NearestFilter; map.minFilter = THREE.NearestFilter;
  return map;
}

function materials(THREE, color, kind, result) {
  const skin = skins[kind === 'walkin' ? 'walkin' : color] || skins.plain;
  // Three.js box order: +X, -X, +Y, -Y, +Z, -Z. +Y is the visible result face.
  return [2, 4, result, 6, 1, 3].map((value, i) => new THREE.MeshLambertMaterial({
    map: faceTexture(THREE, value, skin, i === 2), flatShading: true,
  }));
}

export async function mountDice(canvas, { color = 'plain', kind = 'preorder_plain', result = 1, rolling = false } = {}) {
  const { THREE, RoundedBoxGeometry } = await loadThree();
  if (!canvas.isConnected) return;
  const shouldRoll = rolling && !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: 'low-power' });
  } catch (error) {
    throw error;
  }
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(31, 1, 0.1, 30);
  camera.position.set(3.2, 3.1, 3.5); camera.lookAt(0, 0, 0);
  scene.add(new THREE.HemisphereLight(0xfff8ed, 0x9a7d96, 2.5));
  const light = new THREE.DirectionalLight(0xfff5df, 2.0); light.position.set(-3, 5, 4); scene.add(light);
  const fill = new THREE.DirectionalLight(0xe8c8ef, 1.1); fill.position.set(3, 2, -3); scene.add(fill);
  const group = new THREE.Group(); scene.add(group);
  const mesh = new THREE.Mesh(new RoundedBoxGeometry(1.55, 1.55, 1.55, 1, 0.12), materials(THREE, color, kind, result));
  group.add(mesh);
  const resize = () => {
    if (!canvas.isConnected) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    renderer.setSize(rect.width, rect.height, false);
    camera.aspect = rect.width / rect.height; camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize); observer.observe(canvas); resize();
  let frame = 0, start = performance.now();
  const turns = [2 + Math.floor(Math.random() * 2), 2 + Math.floor(Math.random() * 2), 1 + Math.floor(Math.random() * 2)];
  let resolveAnimation;
  const finished = new Promise(resolve => { resolveAnimation = resolve; });
  let done = false;
  const cleanup = () => {
    if (done) return;
    done = true; cancelAnimationFrame(frame); observer.disconnect(); detachObserver.disconnect();
    renderer.dispose(); mesh.geometry.dispose(); mesh.material.forEach(m => { m.map.dispose(); m.dispose(); });
    resolveAnimation();
  };
  const detachObserver = new MutationObserver(() => { if (!canvas.isConnected) cleanup(); });
  detachObserver.observe(document.body, { childList: true, subtree: true });
  function draw(now) {
    if (!canvas.isConnected) { cleanup(); return; }
    const elapsed = Math.max(0, now - start);
    const progress = shouldRoll ? Math.min(1, elapsed / 1250) : 1;
    const eased = 1 - Math.pow(1 - progress, 3);
    if (shouldRoll && progress < 1) {
      // Keep the die centered in its frame: roll through full turns and add a
      // small hop, without the free-fall translation that could clip it offscreen.
      group.rotation.set(
        Math.PI * 2 * turns[0] * eased,
        Math.PI * 2 * turns[1] * eased,
        Math.PI * 2 * turns[2] * eased,
      );
      group.position.set(0, 0.055 * Math.sin(progress * Math.PI * 6) * (1 - progress), 0);
    } else {
      group.rotation.set(0, 0, 0);
      group.position.set(0, 0, 0);
    }
    renderer.render(scene, camera);
    if (shouldRoll && progress < 1) frame = requestAnimationFrame(draw);
    else resolveAnimation();
  }
  if (shouldRoll) frame = requestAnimationFrame(draw);
  else draw(start);
  return shouldRoll ? finished : undefined;
}
