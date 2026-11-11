const palettes = {
  walkin: { top: '#f8d9ad', left: '#f1c38e', right: '#dfa875', trim: '#d98562', pip: '#51364a', sparkle: '#fff0cf' },
  plain: { top: '#fff6e4', left: '#fff0d5', right: '#f0dfc4', trim: '#e5b85c', pip: '#39271f', sparkle: '#fff8e7' },
  rainbow: { top: '#faf0fc', left: '#f0e2f5', right: '#dfcbe9', trim: '#d99bc8', pip: '#30203f', sparkle: '#fff5ce' },
  silver: { top: '#ffffff', left: '#e5e8ef', right: '#cfd5df', trim: '#b7bfca', pip: '#373642', sparkle: '#ffffff' },
  gold: { top: '#ffe995', left: '#f5d46e', right: '#e8b94a', trim: '#c98112', pip: '#493432', sparkle: '#fff6c9' },
  pink: { top: '#f9d9ef', left: '#f3c5e7', right: '#e4a8d7', trim: '#bd63c8', pip: '#392746', sparkle: '#fff4e1' },
};

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

function faceMark(value, face) {
  if (value === 'milk') {
    const [x, y] = face.point(0.5, 0.5);
    return `<g transform="translate(${x - 2.3} ${y - 2.7})"><path d="M.4 1.2 2 .2h2.1v4.8H.4z" fill="#fff9ed" stroke="#85b8d8" stroke-width=".55"/><path d="M.5 2.8h3.4v1.7H.5z" fill="#8fc8e5"/><path d="M2 .2v1.1h2.1" fill="none" stroke="#bd8d47" stroke-width=".4"/></g>`;
  }
  if (Number(value) > 6) {
    const [x, y] = face.point(0.5, 0.5);
    return `<text x="${x}" y="${y + 1.7}" text-anchor="middle" font-family="monospace" font-size="5.2" font-weight="800" fill="${face.color}">${value}</text>`;
  }
  const positions = pipPositions[Number(value)] || pipPositions[1];
  return positions.map(([col, row]) => {
    const [x, y] = face.point(0.25 + col * 0.25, 0.25 + row * 0.25);
    return `<rect x="${(x - 1.1).toFixed(1)}" y="${(y - 1.1).toFixed(1)}" width="2.2" height="2.2" rx=".35" fill="${face.color}"/>`;
  }).join('');
}

export function diceChoiceArt(kind = 'walkin', color = 'plain') {
  const palette = kind === 'walkin' ? palettes.walkin : kind === 'instagram' ? palettes.pink : palettes[color] || palettes.plain;
  const values = faceSets[kind] || faceSets.walkin;
  const faces = [
    { value: values[0], fill: palette.top, color: palette.pip, path: 'M24 2.5 45 13 24 23.5 3 13', point: (u, v) => [3 + 21 * u + 21 * v, 13 - 10.5 * u + 10.5 * v] },
    { value: values[1], fill: palette.left || palette.walkin, color: palette.pip, path: 'M3 13 24 23.5V46L3 35.5', point: (u, v) => [3 + 21 * u, 13 + 10.5 * u + 22.5 * v] },
    { value: values[2], fill: palette.right, color: palette.pip, path: 'M45 13 24 23.5V46l21-10.5', point: (u, v) => [45 - 21 * u, 13 + 10.5 * u + 22.5 * v] },
  ];
  const marks = faces.map(face => `<g><path d="${face.path}Z" fill="${face.fill}" stroke="${palette.trim}" stroke-width=".9" stroke-linejoin="round"/>${faceMark(face.value, face)}</g>`).join('');
  const gem = kind === 'preorder_gold'
    ? '<path d="M24 5.2 26 7.2 24 9.2 22 7.2z" fill="#fff6c9" stroke="#c98112" stroke-width=".45"/>'
    : kind === 'preorder_rainbow'
      ? '<rect x="8.2" y="11" width="2" height="1.2" fill="#ee8ec1"/><rect x="13" y="8.6" width="2" height="1.2" fill="#f5ce62"/><rect x="18" y="6.1" width="2" height="1.2" fill="#79c9b1"/>'
      : kind === 'preorder_silver'
        ? '<path d="M24 5.4v3.8m-1.9-1.9h3.8" stroke="#fff" stroke-width=".8" stroke-linecap="square"/>'
        : kind === 'instagram'
          ? '<rect x="10" y="8.8" width="2" height="1.2" fill="#f4b23c"/><rect x="14" y="7" width="2" height="1.2" fill="#d34fa1"/><rect x="18" y="5" width="2" height="1.2" fill="#8b58c7"/>'
          : kind === 'walkin'
            ? '<rect x="10" y="9" width="1.3" height="1.3" rx=".3" fill="#fff0cf"/><rect x="15" y="7" width="1.3" height="1.3" rx=".3" fill="#fff0cf"/>'
            : '<path d="M24 5.6v3m-1.5-1.5h3" stroke="#fff8e7" stroke-width=".7" stroke-linecap="square"/>';
  return `<svg class="dice-choice-art" viewBox="0 0 48 48" role="img" aria-label="${kind} 주사위 미리보기" xmlns="http://www.w3.org/2000/svg"><path d="M3 13 24 2.5 45 13 45 35.5 24 46 3 35.5z" fill="${palette.top}" opacity=".16"/>${marks}${gem}</svg>`;
}
