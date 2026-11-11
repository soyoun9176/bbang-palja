let threePromise;
const skins = {
  walkin: { id: 'walkin', face: '#f1c38e', trim: '#d98562', pip: '#51364a', glint: '#fff0cf' },
  plain: { id: 'plain', face: '#fff0d5', trim: '#e5b85c', pip: '#39271f', glint: '#fff8e7' },
  rainbow: { id: 'rainbow', face: '#f0e2f5', trim: '#d99bc8', pip: '#30203f', glint: '#fff5ce' },
  silver: { id: 'silver', face: '#e5e8ef', trim: '#b7bfca', pip: '#373642', glint: '#ffffff' },
  gold: { id: 'gold', face: '#f5d46e', trim: '#c98112', pip: '#493432', glint: '#fff6c9' },
  pink: { id: 'pink', face: '#f3c5e7', trim: '#bd63c8', pip: '#392746', glint: '#fff4e1' },
};
// Keep the client artwork aligned with the server's six equally likely face slots.
const faceSets = {
  walkin: [1, 2, 3, 3, 4, 5],
  preorder_plain: [1, 2, 3, 4, 5, 6],
  preorder_rainbow: [2, 2, 3, 5, 6, 12],
  preorder_silver: [3, 5, 7, 9, 11, 18],
  preorder_gold: ['milk', 6, 9, 11, 15, 22],
  instagram: [1, 1, 2, 2, 3, 'milk'],
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
  // Each preorder tier gets its own pixel-art trim while keeping the pips clear.
  ctx.fillStyle = skin.glint;
  ctx.fillRect(8, 8, 12, 3); ctx.fillRect(8, 8, 3, 12);
  ctx.fillStyle = skin.trim;
  [[8, 8, 8, 2], [8, 8, 2, 8], [48, 8, 8, 2], [54, 8, 2, 8],
    [8, 54, 8, 2], [8, 48, 2, 8], [48, 54, 8, 2], [54, 48, 2, 8]]
    .forEach(([x, y, w, h]) => ctx.fillRect(x, y, w, h));
  if (skin.id === 'rainbow') {
    const blocks = ['#ee8ec1', '#f5ce62', '#79c9b1', '#72b9e0', '#ae8bd1'];
    // Small prism shards live in the corners and side rails, never under the pips.
    [[7, 10], [51, 10], [7, 46], [51, 46]].forEach(([x, y], corner) => {
      ctx.fillStyle = blocks[corner]; ctx.fillRect(x, y, 3, 3);
      ctx.fillStyle = blocks[(corner + 1) % blocks.length]; ctx.fillRect(x + (corner % 2 ? -3 : 3), y + 4, 2, 2);
      ctx.fillStyle = blocks[(corner + 3) % blocks.length]; ctx.fillRect(x, y + 7, 2, 2);
    });
    ctx.fillStyle = '#fff5ce';
    [[9, 31], [52, 31]].forEach(([x, y]) => { ctx.fillRect(x + 2, y, 2, 6); ctx.fillRect(x, y + 2, 6, 2); });
  }
  if (skin.id === 'silver') {
    // Cool silver laurel pixels frame the face instead of a gold-colored border.
    for (let i = 0; i < 6; i++) {
      const y = 13 + i * 7, inset = i % 2 ? 2 : 0;
      ctx.fillStyle = i % 2 ? '#c4cad5' : '#ffffff';
      ctx.fillRect(5 + inset, y, 4, 3); ctx.fillRect(55 - inset, y, 4, 3);
      ctx.fillRect(9 + inset, y + 3, 3, 2); ctx.fillRect(52 - inset, y + 3, 3, 2);
    }
    ctx.fillStyle = '#ffffff';
    [[31, 7], [31, 53]].forEach(([x, y]) => { ctx.fillRect(x + 2, y, 2, 6); ctx.fillRect(x, y + 2, 6, 2); });
  }
  if (skin.id === 'gold') {
    // A cute, richly layered pixel filigree with little jewel-like corner stars.
    ctx.fillStyle = '#a9690c';
    [[6, 6], [52, 6], [6, 52], [52, 52]].forEach(([x, y], i) => {
      const sx = i % 2 ? -1 : 1, sy = i > 1 ? -1 : 1;
      ctx.fillRect(x, y, 9, 2); ctx.fillRect(x, y, 2, 9);
      ctx.fillRect(x + sx * 3, y + sy * 3, 2, 2);
      ctx.fillStyle = '#fff6c9'; ctx.fillRect(x + sx * 5, y + sy * 5, 3, 3);
      ctx.fillStyle = '#d98b22'; ctx.fillRect(x + sx * 5, y + sy * 5, 1, 1);
      ctx.fillStyle = '#a9690c';
    });
    ctx.fillStyle = '#fff6c9';
    [[8, 29], [54, 29], [29, 8], [29, 54]].forEach(([x, y]) => { ctx.fillRect(x + 2, y, 2, 7); ctx.fillRect(x, y + 2, 6, 2); });
    ctx.fillStyle = '#d986c3';
    [[13, 13], [47, 13], [13, 47], [47, 47]].forEach(([x, y]) => { ctx.fillRect(x + 2, y, 3, 2); ctx.fillRect(x, y + 2, 7, 2); ctx.fillRect(x + 2, y + 4, 3, 2); });
  }
  if (skin.id === 'walkin') {
    // Soft toast-colored corner marks and sesame pixels keep the bakery theme cute.
    ctx.fillStyle = '#bd704e';
    [[10, 10], [50, 10], [10, 50], [50, 50]].forEach(([x, y], i) => {
      const sx = i % 2 ? -1 : 1, sy = i > 1 ? -1 : 1;
      ctx.fillRect(x, y, 5, 2); ctx.fillRect(x, y, 2, 5);
      ctx.fillStyle = '#fff0cf'; ctx.fillRect(x + sx * 3, y + sy * 3, 2, 2); ctx.fillStyle = '#bd704e';
    });
    ctx.fillStyle = '#ffe7bb';
    [[14, 28], [47, 35], [28, 48], [35, 14]].forEach(([x, y]) => ctx.fillRect(x, y, 2, 2));
  }
  if (skin.id === 'pink') {
    // Instagram-inspired pixel ribbon kept on the outer rails, clear of pips.
    const blocks = ['#f4b23c', '#ee6b55', '#d34fa1', '#8b58c7', '#5f76cb'];
    for (let i = 0; i < blocks.length; i++) {
      ctx.fillStyle = blocks[i];
      ctx.fillRect(15 + i * 7, 7, 4, 3);
      ctx.fillRect(15 + i * 7, 54, 4, 3);
    }
    ctx.fillStyle = '#fff4e1';
    [[8, 29], [54, 29]].forEach(([x, y]) => { ctx.fillRect(x + 1, y, 2, 5); ctx.fillRect(x, y + 1, 4, 2); });
  }
  // The pip is deliberately flat, large, and high contrast so it stays clear at phone size.
  if (value === 'milk') {
    ctx.fillStyle = '#fff8e8'; ctx.fillRect(18, 12, 28, 40);
    ctx.fillStyle = skin.trim; ctx.fillRect(18, 23, 28, 10);
    ctx.fillStyle = skin.pip; ctx.font = 'bold 10px sans-serif'; ctx.textAlign = 'center';
    ctx.textBaseline = 'middle'; ctx.fillText('우유', 32, 40);
  } else if (Number(value) >= 7) {
    ctx.fillStyle = skin.pip; ctx.font = 'bold 26px monospace'; ctx.textAlign = 'center';
    ctx.textBaseline = 'middle'; ctx.fillText(String(value), 32, 32);
    ctx.fillStyle = skin.glint; ctx.fillRect(19, 47, 26, 2);
  } else {
    const spots = pipPositions[Number(value)] || pipPositions[1];
    for (const [col, row] of spots) {
      // Treat each coordinate as the pip center on a symmetric 3×3 grid.
      const centerX = 18 + col * 14, centerY = 18 + row * 14;
      const x = centerX - 6, y = centerY - 6;
      ctx.fillStyle = skin.pip;
      ctx.fillRect(x + 2, y, 8, 3);
      ctx.fillRect(x, y + 3, 12, 6);
      ctx.fillRect(x + 2, y + 9, 8, 3);
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
  const faces = [...(faceSets[kind] || faceSets.walkin)];
  const resultIndex = result == null ? 0 : faces.findIndex(value => value === 'milk' ? result === 'milk' : Number(value) === Number(result));
  const topIndex = resultIndex < 0 ? 0 : resultIndex;
  const top = faces.splice(topIndex, 1)[0];
  // Three.js box order: +X, -X, +Y, -Y, +Z, -Z. Put the server result on +Y.
  return [faces[0], faces[1], top, faces[2], faces[3], faces[4]].map((value, i) => new THREE.MeshLambertMaterial({
    map: faceTexture(THREE, value, skin, i === 2), flatShading: true,
  }));
}

export async function mountDice(canvas, { color = 'plain', kind = 'preorder_plain', result = null, rolling = false } = {}) {
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
