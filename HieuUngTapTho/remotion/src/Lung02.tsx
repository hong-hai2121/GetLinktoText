import React from 'react';
import {AbsoluteFill, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import SUBS from './lung02_sub.json';
import {Check, Fx, FxOne, HoldClock, Label} from './Lung01';

// Video 02.mov (nối tiếp 01): toàn bộ là cảnh ngồi nói → phủ kín cả khung bằng cảnh vẽ,
// hình nhân mặc áo blouse trắng + quần be + tất trắng (giống người thật ở video 01) tập động tác 6–8.
export const LUNG02_FRAMES = 2734; // 91.14 s
const FPS = 30;

type P = {x: number; y: number};
const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ramp = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
const ease = (x: number) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const sm = (t: number, a: number, b: number) => ease(ramp(t, a, b));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const lp = (a: P, b: P, k: number): P => ({x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k)});
const add = (a: P, x: number, y: number): P => ({x: a.x + x, y: a.y + y});
const pol = (a: P, len: number, deg: number): P => ({x: a.x + Math.cos((deg * Math.PI) / 180) * len, y: a.y + Math.sin((deg * Math.PI) / 180) * len});
const pop = (t: number, t0: number) => {
  const x = t - t0;
  if (x <= 0) return 0;
  if (x > 0.6) return 1;
  return 1 + Math.sin(x * 10) * Math.exp(-x * 8) * 0.9 - Math.exp(-x * 14) * 1;
};
const fadeIO = (t: number, a: number, b: number, d = 0.25) => Math.min(ramp(t, a, a + d), 1 - ramp(t, b - d, b));

const FONT = "'Segoe UI Black', 'Segoe UI', sans-serif";
const FONT_B = "'Segoe UI', sans-serif";
const SERIF = "'Times New Roman', Times, serif";
const C = {
  navy: '#0b2236',
  teal: '#12a89c',
  red: '#e53935',
  yellow: '#ffd54a',
  skin: '#f1c39a',
  skinD: '#d79d72',
  skinL: '#f8d6b6',
  hair: '#1f1712',
  coat: '#ffffff',
  coatD: '#cfd8e3',
  pants: '#e3d3b4',
  pantsD: '#bfa982',
  sock: '#f7f7f7',
  sockD: '#d4d8de',
};
const BED = 1180; // mặt giường

const ik = (a: P, b: P, l1: number, l2: number, up: boolean): P => {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const d = Math.min(Math.hypot(dx, dy), l1 + l2 - 0.01);
  const k = (l1 * l1 - l2 * l2 + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, l1 * l1 - k * k));
  const ux = dx / d;
  const uy = dy / d;
  const m = {x: a.x + ux * k, y: a.y + uy * k};
  const c1 = {x: m.x - uy * h, y: m.y + ux * h};
  const c2 = {x: m.x + uy * h, y: m.y - ux * h};
  return (c1.y < c2.y) === up ? c1 : c2;
};

// ===================== VẼ HÌNH NHÂN =====================
// đoạn chi thon dần: hai đường tròn nối bằng tiếp tuyến ngoài
const limbPath = (a: P, b: P, ra: number, rb: number) => {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const d = Math.hypot(dx, dy) || 1;
  const ux = dx / d;
  const uy = dy / d;
  const nx = -uy;
  const ny = ux;
  const s = (ra - rb) / d;
  const c = Math.sqrt(Math.max(0, 1 - s * s));
  const ox = nx * c + ux * s;
  const oy = ny * c + uy * s;
  const ox2 = -nx * c + ux * s;
  const oy2 = -ny * c + uy * s;
  return `M ${a.x + ox * ra} ${a.y + oy * ra} L ${b.x + ox * rb} ${b.y + oy * rb} A ${rb} ${rb} 0 0 0 ${b.x + ox2 * rb} ${b.y + oy2 * rb} L ${a.x + ox2 * ra} ${a.y + oy2 * ra} A ${ra} ${ra} 0 0 0 ${a.x + ox * ra} ${a.y + oy * ra} Z`;
};
const Limb: React.FC<{a: P; b: P; ra: number; rb: number; fill: string; stroke: string}> = ({a, b, ra, rb, fill, stroke}) => (
  <path d={limbPath(a, b, ra, rb)} fill={fill} stroke={stroke} strokeWidth={3} strokeLinejoin="round" />
);

// đầu: ang = hướng mặt nhìn (độ, 0 = phải, 90 = xuống, 180 = trái)
const Dau: React.FC<{H: P; ang: number}> = ({H, ang}) => {
  const left = Math.cos((ang * Math.PI) / 180) < 0;
  const a2 = left ? 180 - ang : ang;
  return (
    <g transform={`translate(${H.x} ${H.y}) scale(${left ? -1 : 1} 1) rotate(${a2})`}>
      <ellipse cx={-10} cy={-6} rx={56} ry={58} fill={C.hair} />
      <ellipse cx={6} cy={6} rx={50} ry={58} fill="url(#gSkin)" stroke={C.skinD} strokeWidth={3} />
      <path d="M 50 -6 Q 64 12 54 20 Q 50 22 47 20" fill={C.skin} stroke={C.skinD} strokeWidth={3} strokeLinejoin="round" />
      <ellipse cx={-14} cy={8} rx={11} ry={16} fill={C.skinD} />
      <ellipse cx={-13} cy={8} rx={6} ry={10} fill={C.skin} />
      <path d="M -60 4 Q -66 -58 -2 -68 Q 52 -70 60 -22 Q 40 -40 10 -38 Q -20 -36 -34 -10 Q -40 4 -42 18 Z" fill={C.hair} />
      <path d="M 22 -16 Q 34 -22 46 -16" stroke={C.hair} strokeWidth={6} fill="none" strokeLinecap="round" />
      <ellipse cx={36} cy={-4} rx={5} ry={4.5} fill="#2b1d14" />
      <path d="M 38 36 Q 46 38 50 34" stroke="#b05f55" strokeWidth={4} fill="none" strokeLinecap="round" />
    </g>
  );
};

// bàn chân đi tất: gót tại A, ang = hướng mũi chân (độ)
const BanChan: React.FC<{A: P; ang: number; dark?: boolean}> = ({A, ang, dark}) => (
  <g transform={`translate(${A.x} ${A.y}) rotate(${ang})`}>
    <path
      d="M -22 -20 Q -38 -2 -24 20 Q 10 30 70 22 Q 104 18 106 2 Q 106 -14 84 -18 Q 40 -24 -22 -20 Z"
      fill={dark ? C.sockD : C.sock}
      stroke="#b9c0c9"
      strokeWidth={3}
    />
    <path d="M 70 -16 Q 96 -10 100 4" stroke="#c9ced6" strokeWidth={3} fill="none" />
  </g>
);

const Ban: React.FC<{W: P; ang: number; dark?: boolean}> = ({W, ang, dark}) => (
  <g transform={`translate(${W.x} ${W.y}) rotate(${ang})`}>
    <ellipse cx={18} cy={0} rx={30} ry={20} fill={dark ? C.skinD : C.skin} stroke={C.skinD} strokeWidth={3} />
    <ellipse cx={10} cy={-16} rx={14} ry={8} fill={dark ? C.skinD : C.skin} stroke={C.skinD} strokeWidth={2.5} transform="rotate(-20 10 -16)" />
  </g>
);

type Pose = {
  H: P;
  hAng: number;
  S: P;
  Pv: P;
  K: P;
  A: P;
  fAng: number;
  E: P;
  W: P;
  wAng: number;
  far: {K: P; A: P; fAng: number; E: P; W: P; wAng: number};
};

const NguoiTap: React.FC<{p: Pose; o?: number}> = ({p, o = 1}) => {
  const neckA = lp(p.S, p.H, 0.15);
  const neckB = lp(p.S, p.H, 0.7);
  const tdir = {x: p.Pv.x - p.S.x, y: p.Pv.y - p.S.y};
  const tl = Math.hypot(tdir.x, tdir.y);
  const hl = Math.abs(tdir.y) > Math.abs(tdir.x) ? 0 : 40;
  const hem = {x: p.Pv.x + (tdir.x / tl) * hl, y: p.Pv.y + (tdir.y / tl) * hl};
  const f = p.far;
  return (
    <g opacity={o}>
      {/* bóng trên giường */}
      <ellipse cx={(Math.min(p.H.x, p.A.x) + Math.max(p.H.x, p.A.x)) / 2} cy={BED + 6} rx={Math.abs(p.A.x - p.H.x) / 2 + 60} ry={16} fill="#000" opacity={0.18} filter="url(#blur8)" />
      {/* tay + chân phía sau */}
      <Limb a={p.S} b={f.E} ra={30} rb={26} fill={C.coatD} stroke="#a9b4c2" />
      <Limb a={f.E} b={f.W} ra={22} rb={17} fill={C.skinD} stroke="#c08560" />
      <Ban W={f.W} ang={f.wAng} dark />
      <Limb a={p.Pv} b={f.K} ra={46} rb={36} fill={C.pantsD} stroke="#a58f68" />
      <Limb a={f.K} b={f.A} ra={34} rb={24} fill={C.pantsD} stroke="#a58f68" />
      <BanChan A={f.A} ang={f.fAng} dark />
      {/* cổ + đầu */}
      <Limb a={neckA} b={neckB} ra={26} rb={24} fill={C.skin} stroke={C.skinD} />
      <Dau H={p.H} ang={p.hAng} />
      {/* thân áo blouse */}
      <Limb a={p.S} b={hem} ra={64} rb={62} fill="url(#gCoat)" stroke="#b7c2cf" />
      <path d={`M ${lp(p.S, p.Pv, 0.08).x} ${lp(p.S, p.Pv, 0.08).y} L ${lp(p.S, p.Pv, 0.95).x} ${lp(p.S, p.Pv, 0.95).y}`} stroke="#dfe5ec" strokeWidth={5} strokeLinecap="round" />
      <Limb a={lp(p.S, neckB, 0.12)} b={lp(p.S, p.Pv, 0.22)} ra={20} rb={8} fill="#f1f4f8" stroke="#b7c2cf" />
      {/* chân phía trước */}
      <Limb a={p.Pv} b={p.K} ra={50} rb={38} fill="url(#gPants)" stroke={C.pantsD} />
      <Limb a={p.K} b={p.A} ra={36} rb={25} fill="url(#gPants)" stroke={C.pantsD} />
      <BanChan A={p.A} ang={p.fAng} />
      {/* tay phía trước */}
      <Limb a={p.S} b={p.E} ra={32} rb={27} fill="url(#gCoat)" stroke="#b7c2cf" />
      <Limb a={lp(p.S, p.E, 0.98)} b={p.W} ra={22} rb={17} fill={C.skin} stroke={C.skinD} />
      <Ban W={p.W} ang={p.wAng} />
    </g>
  );
};

// --- động tác 6: châu chấu (nằm sấp, đầu bên trái) ---
const proneLocust = (chest: number, legs: number): Pose => {
  const Pv = {x: 600, y: 1128};
  const S = {x: 350, y: 1130 - 46 * chest};
  const H = {x: 228, y: 1118 - 78 * chest};
  const K = {x: 812, y: 1140 - 14 * legs};
  const A = {x: 1000, y: 1150 - 40 * legs};
  return {
    H,
    hAng: lerp(150, 182, chest),
    S,
    Pv,
    K,
    A,
    fAng: lerp(4, -4, legs),
    E: {x: 450, y: 1150 - 30 * chest},
    W: {x: 565, y: 1158 - 26 * chest},
    wAng: 0,
    far: {K: add(K, 6, -14), A: add(A, 6, -12), fAng: lerp(0, -8, legs), E: {x: 450, y: 1136 - 30 * chest}, W: {x: 560, y: 1142 - 26 * chest}, wAng: 0},
  };
};

// --- ngồi duỗi chân (động tác 7, 8): hông bên trái, chân duỗi sang phải ---
const SIT_P = {x: 330, y: 1128};
const longSit = (o: {lean?: number; back?: number; pull?: number; strap?: number; knee?: number; patY?: number; patX?: number; reach?: number}): Pose => {
  const lean = o.lean ?? 0; // cúi về trước 0..1 (45°)
  const back = o.back ?? 0; // ngả nhẹ ra sau khi kéo dây
  const th = 45 * lean - 6 * back;
  const S = pol(SIT_P, 255, -90 + th);
  const H = pol(S, 118, -90 + th - 4);
  const K = {x: 545, y: 1140};
  const A = {x: 752, y: 1144};
  const pull = o.pull ?? 0;
  const fAng = lerp(-78, -100, pull);
  // tay
  let W: P;
  let wAng = 0;
  const strap = o.strap ?? 0;
  const knee = o.knee ?? 0;
  const reach = o.reach ?? 0;
  const restW = {x: 470, y: 1100};
  const strapW = {x: lerp(570, 520, pull), y: lerp(1010, 1000, pull)};
  const kneeW = {x: K.x + (o.patX ?? 0) - 6, y: K.y - 58 + (o.patY ?? 0)};
  const reachW = {x: lerp(560, 690, lean), y: lerp(1080, 1108, lean)};
  W = restW;
  W = lp(W, strapW, strap);
  W = lp(W, kneeW, knee);
  W = lp(W, reachW, reach);
  wAng = lerp(10, -15, strap);
  const E = ik(S, W, 160, 150, false);
  return {
    H,
    hAng: lerp(4, 30, lean) - 8 * back,
    S,
    Pv: SIT_P,
    K,
    A,
    fAng,
    E,
    W,
    wAng,
    far: {K: add(K, 10, -12), A: add(A, 12, -12), fAng: fAng + 2, E: add(E, 14, -10), W: add(W, 14, -10), wAng},
  };
};

// ===================== DÒNG THỜI GIAN =====================
type Ex = {n: number; name: string; start: number; end: number; info: string; idle: string};
const EXS: Ex[] = [
  {n: 6, name: 'CHÂU CHẤU', start: 0, end: 27.08, info: 'giữ khoảng 5 giây', idle: 'NÂNG NHẸ NGỰC VÀ 2 CHÂN'},
  {n: 7, name: 'DÃN BẮP CHUỐI BẰNG DÂY', start: 27.08, end: 53.82, info: 'giữ khoảng 10 giây', idle: 'KÉO DÂY ĐẾN KHI HƠI CĂNG'},
  {n: 8, name: 'DÃN CƠ SAU ĐÙI', start: 53.82, end: 73.12, info: 'giữ 15–20 giây', idle: 'CÚI NGƯỜI VỀ TRƯỚC'},
];
const END_AT = 73.12;

type FxZ = {type: string; zone?: string; zones?: string[]; d?: number[]; curve?: number; kind?: string; off?: number[]; slow?: number};
type Cue = {t: number; e: number; text: string; sub?: string; hold?: number; zone?: string; tag?: string; kind?: string; fx?: FxZ[]};
const CUES: Cue[] = [
  {t: 3.22, e: 5.45, text: 'GIỮ KHOẢNG 5 GIÂY', hold: 5},
  {t: 6.8, e: 9.3, text: 'NẰM SẤP · TAY XUÔI THEO THÂN', zone: 'arm', tag: 'TAY XUÔI', fx: [{type: 'beam', zones: ['shoulder', 'hand']}]},
  {t: 9.32, e: 11.42, text: 'SIẾT MÔNG · NÂNG NHẸ NGỰC', zone: 'glute', tag: 'SIẾT MÔNG', fx: [{type: 'arrow', zone: 'chest', d: [0, -170]}]},
  {t: 11.46, e: 14.18, text: 'NÂNG 2 CHÂN KHỎI SÀN', sub: 'chỉ vài phân thôi', zone: 'ankle', tag: 'VÀI PHÂN', fx: [{type: 'arrow', zone: 'ankle', d: [0, -130]}]},
  {t: 14.2, e: 16.2, text: 'KHÔNG CẦN NÂNG QUÁ CAO', kind: 'no', zone: 'ankle', tag: 'VỪA ĐỦ', fx: [{type: 'mark', zone: 'ankle', kind: 'no', off: [-110, -150]}]},
  {t: 16.24, e: 19.85, text: 'KÍCH HOẠT CƠ LƯNG DƯỚI', sub: 'chỉ cần vài phân là đủ', zone: 'lowback', tag: 'LƯNG DƯỚI', fx: [{type: 'mark', zone: 'lowback', kind: 'ok', off: [110, -120]}]},
  {t: 19.88, e: 24.84, text: 'GIỮ KHOẢNG 5 GIÂY', hold: 5, zone: 'lowback', tag: 'LƯNG DƯỚI'},
  {t: 31.18, e: 33.35, text: 'GIỮ KHOẢNG 10 GIÂY', hold: 10},
  {t: 33.38, e: 35.0, text: 'NGỒI DUỖI 2 CHÂN', sub: 'trên giường', zone: 'knee', tag: 'DUỖI THẲNG', fx: [{type: 'beam', zones: ['hip', 'ankle']}]},
  {t: 35.04, e: 36.38, text: 'VÒNG DÂY HOẶC KHĂN', sub: 'qua lòng bàn chân', zone: 'sole', tag: 'LÒNG BÀN CHÂN'},
  {t: 36.4, e: 38.4, text: 'KÉO VỀ PHÍA MÌNH', zone: 'hand', tag: 'KÉO', fx: [{type: 'arrow', zone: 'hand', d: [-170, -20]}]},
  {t: 38.42, e: 40.02, text: 'HƠI CĂNG THÌ DỪNG', zone: 'calf', tag: 'BẮP CHUỐI', fx: [{type: 'mark', zone: 'calf', kind: 'ok', off: [150, -110]}]},
  {t: 40.04, e: 43.4, text: 'KHÔNG KÉO QUÁ MỨC', sub: 'không cố dãn quá', kind: 'no', zone: 'calf', tag: 'BẮP CHUỐI', fx: [{type: 'mark', zone: 'sole', kind: 'no', off: [110, -40]}]},
  {t: 43.6, e: 45.0, text: 'THẢ LỎNG ĐÙI', zone: 'thigh', tag: 'ĐÙI THẢ LỎNG'},
  {t: 45.02, e: 48.08, text: 'DI XƯƠNG BÁNH CHÈ', sub: 'lên xuống · qua lại', zone: 'kneecap', tag: 'BÁNH CHÈ', fx: [{type: 'cross', zone: 'kneecap'}]},
  {t: 48.1, e: 52.56, text: 'ĐỠ ĐAU HƠN RẤT NHIỀU', kind: 'ok', zone: 'kneecap', tag: 'GỐI', fx: [{type: 'mark', zone: 'kneecap', kind: 'ok', off: [120, -60]}]},
  {t: 56.18, e: 59.1, text: 'NGỒI THẲNG · CHÂN TRÊN GIƯỜNG', zone: 'back', tag: 'LƯNG THẲNG', fx: [{type: 'line', zones: ['hip', 'shoulder']}]},
  {t: 59.18, e: 64.4, text: 'CÚI NGƯỜI VỀ PHÍA TRƯỚC', sub: 'đến khi căng phần sau đùi', zone: 'hamstring', tag: 'SAU ĐÙI', fx: [{type: 'arrow', zone: 'head', d: [150, 70], curve: -40}]},
  {t: 64.42, e: 69.62, text: 'BỊ LOÃNG XƯƠNG?', sub: 'giữ lưng thẳng · nghiêng nhẹ', kind: 'ok', zone: 'back', tag: 'LƯNG THẲNG', fx: [{type: 'line', zones: ['hip', 'shoulder']}, {type: 'mark', zone: 'back', kind: 'ok', off: [-130, -40]}]},
  {t: 69.66, e: 73.1, text: 'GIỮ 15–20 GIÂY', hold: 15, zone: 'hamstring', tag: 'SAU ĐÙI'},
];

const RULES: {t: number; text: string; bad?: boolean}[] = [
  {t: 75.36, text: 'Tập nhẹ nhàng'},
  {t: 76.86, text: 'Mỗi lần giữ ngắn 10–15 giây'},
  {t: 80.02, text: 'Tập nhiều lần trong ngày'},
  {t: 80.94, text: 'Dừng ngay khi thấy khó chịu', bad: true},
  {t: 85.24, text: 'Tập đều đặn cả 2 chân'},
  {t: 87.66, text: 'Kể cả khi đã đỡ đau hẳn'},
];

type Cam = {k: number; dx: number};
const camOf = (t: number): Cam => (t < 27.15 ? {k: 1.04, dx: -60} : {k: 1.3, dx: 0});
const mapPt = (c: Cam, q: P): P => ({x: 540 + (q.x - 540) * c.k + c.dx, y: BED + (q.y - BED) * c.k});

const poseAt = (t: number): {pose: Pose; strap: number; ex: number} => {
  if (t < 27.08) {
    const up = 1 - sm(t, 24.84, 26.2);
    return {pose: proneLocust(sm(t, 9.6, 11.0) * up, sm(t, 11.7, 13.0) * up), strap: 0, ex: 6};
  }
  if (t < 53.82) {
    const strap = sm(t, 35.04, 35.9) * (1 - sm(t, 43.6, 44.4));
    const pull = sm(t, 36.4, 38.42) * (1 - sm(t, 43.6, 44.4));
    const knee = sm(t, 44.0, 45.0) * (1 - sm(t, 50.5, 51.6));
    let patY = 0;
    let patX = 0;
    if (t >= 45.02 && t < 47.4) patY = 12 * Math.sin((t - 45.02) * 7);
    if (t >= 47.4 && t < 50.5) patX = 12 * Math.sin((t - 47.4) * 7);
    return {pose: longSit({strap, pull, back: pull, knee, patY, patX}), strap, ex: 7};
  }
  let lean = sm(t, 59.18, 61.0);
  if (t >= 64.42) lean = lerp(1, 0.42, sm(t, 64.42, 65.8));
  lean *= 1 - sm(t, 73.12, 74.4);
  const reach = t < 64.42 ? lean : lean / 0.42 * 0.6;
  return {pose: longSit({lean, reach: clamp(reach)}), strap: 0, ex: 8};
};

let CAM: Cam = {k: 1, dx: 0};
const zonePt = (p: Pose, z: string): P => mapPt(CAM, zoneRaw(p, z));
const zoneRaw = (p: Pose, z: string): P => {
  switch (z) {
    case 'arm':
      return lp(p.E, p.W, 0.4);
    case 'shoulder':
      return p.S;
    case 'hand':
      return p.W;
    case 'chest':
      return lp(p.S, p.Pv, 0.12);
    case 'glute':
      return add(p.Pv, 10, -50);
    case 'ankle':
      return add(p.A, 30, 0);
    case 'lowback':
      return add(lp(p.Pv, p.S, 0.28), 0, -50);
    case 'hip':
      return p.Pv;
    case 'knee':
      return p.K;
    case 'kneecap':
      return add(p.K, 0, -44);
    case 'sole':
      return pol(p.A, 55, p.fAng);
    case 'calf':
      return add(lp(p.K, p.A, 0.5), 0, 16);
    case 'thigh':
      return add(lp(p.Pv, p.K, 0.55), 0, -20);
    case 'back':
      return lp(p.Pv, p.S, 0.5);
    case 'hamstring':
      return add(lp(p.Pv, p.K, 0.5), 0, 28);
    case 'head':
      return p.H;
    default:
      return p.Pv;
  }
};

// ===================== CẢNH PHÒNG =====================
const Room: React.FC = () => (
  <g>
    <rect x={0} y={0} width={1080} height={1920} fill="url(#gWall)" />
    {/* rèm cửa sổ */}
    <rect x={110} y={470} width={520} height={470} rx={8} fill="#b08f62" />
    {Array.from({length: 13}).map((_, i) => (
      <rect key={i} x={118} y={478 + i * 35} width={504} height={30} rx={4} fill={i % 2 ? '#d6b98c' : '#ceb083'} />
    ))}
    <rect x={110} y={470} width={520} height={470} rx={8} fill="url(#gShine)" />
    {/* bảng trắng */}
    <rect x={720} y={500} width={280} height={190} rx={8} fill="#f8f9fb" stroke="#c9ced6" strokeWidth={6} />
    {/* giường */}
    <rect x={20} y={BED - 6} width={1040} height={86} rx={26} fill="url(#gBed)" />
    <rect x={20} y={BED + 70} width={1040} height={40} rx={12} fill="#8d6e63" />
    <rect x={50} y={BED + 100} width={36} height={130} rx={8} fill="#6d4c41" />
    <rect x={994} y={BED + 100} width={36} height={130} rx={8} fill="#6d4c41" />
    <rect x={0} y={BED + 220} width={1080} height={520} fill="#d9cfc6" />
  </g>
);

// ===================== LỚP CHỮ =====================
const TitleBar: React.FC = () => (
  <div
    style={{
      position: 'absolute',
      left: 50,
      top: 28,
      width: 980,
      height: 126,
      borderRadius: 30,
      background: '#ffffff',
      border: '8px solid #1e88e5',
      boxShadow: '0 10px 30px rgba(0,0,0,0.3)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: SERIF,
      fontWeight: 700,
      fontSize: 68,
      whiteSpace: 'nowrap',
    }}
  >
    <span style={{color: '#111'}}>BÀI TẬP LƯNG&nbsp;</span>
    <span style={{color: C.red}}>8 ĐỘNG TÁC</span>
  </div>
);

const Chip: React.FC<{pill: string; name: string; info: string; t: number; t0: number; t1: number}> = ({pill, name, info, t, t0, t1}) => {
  const s = t0 <= 0.01 ? 1 : pop(t, t0);
  const o = t0 <= 0.01 ? 1 - ramp(t, t1 - 0.2, t1) : fadeIO(t, t0, t1 + 0.1, 0.2);
  const flash = t0 <= 0.01 ? 0 : Math.exp(-(t - t0) * 3);
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        top: 172,
        width: 960,
        height: 250,
        borderRadius: 34,
        background: `linear-gradient(135deg, ${C.teal}, #0d6e8c)`,
        boxShadow: `0 12px 34px rgba(0,0,0,0.35), 0 0 ${60 * flash}px ${30 * flash}px rgba(255,213,74,${0.8 * flash})`,
        opacity: o,
        transform: `scale(${s})`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#fff',
      }}
    >
      <div style={{fontFamily: FONT, fontSize: 40, background: C.yellow, color: C.navy, padding: '2px 26px', borderRadius: 40, letterSpacing: 2}}>{pill}</div>
      <div style={{fontFamily: FONT, fontSize: name.length > 16 ? 64 : 86, lineHeight: 1.1, marginTop: 6, textShadow: '0 4px 12px rgba(0,0,0,0.3)', whiteSpace: 'nowrap'}}>{name}</div>
      <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 40, color: '#e9fffb'}}>{info}</div>
    </div>
  );
};

const Panel: React.FC<{t: number; text: string; cue?: Cue; key0: number}> = ({t, text, cue, key0}) => {
  const s = pop(t, key0);
  const icon = cue && (cue.kind === 'ok' || cue.kind === 'no');
  const side = icon || cue?.hold ? 120 : 0;
  return (
    <div
      style={{
        position: 'absolute',
        left: 40,
        top: 1560,
        width: 1000,
        height: 220,
        borderRadius: 36,
        background: 'rgba(11,34,54,0.9)',
        border: '4px solid rgba(255,255,255,0.25)',
        boxShadow: '0 10px 30px rgba(0,0,0,0.3)',
        transform: `scale(${s})`,
        display: 'flex',
        alignItems: 'center',
      }}
    >
      {icon ? (
        <svg viewBox="-60 -60 120 120" style={{position: 'absolute', left: 20, top: 50, width: 120, height: 120}}>
          <Check x={0} y={0} ok={cue!.kind === 'ok'} s={1.4 * pop(t, cue!.t + 0.15)} />
        </svg>
      ) : null}
      <div style={{position: 'absolute', left: side, right: side, textAlign: 'center'}}>
        <div style={{fontFamily: FONT, fontSize: side ? (text.length > 16 ? 48 : 60) : text.length > 20 ? 54 : 66, color: cue?.kind === 'no' ? '#ff8a80' : '#ffffff', lineHeight: 1.1}}>{text}</div>
        {cue?.sub ? <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 40, color: C.yellow, marginTop: 6}}>{cue.sub}</div> : null}
      </div>
      {cue?.hold ? (
        <svg viewBox="812 40 120 120" style={{position: 'absolute', right: 10, top: 50, width: 120, height: 120}}>
          <HoldClock t={t} t0={cue.t} n={cue.hold} />
        </svg>
      ) : null}
    </div>
  );
};

// ===================== HIỆU ỨNG TRÊN HÌNH NHÂN =====================
const BodyLayer: React.FC<{t: number; f: number; pose: Pose; cue?: Cue}> = ({t, f, pose, cue}) => {
  if (!cue) return null;
  const o = fadeIO(t, cue.t, cue.e, 0.2);
  const s = pop(t, cue.t);
  const pulse = 0.5 + 0.5 * Math.sin(f / 3.2);
  const col = cue.kind === 'no' ? '#ff5252' : '#ffe14d';
  const z = cue.zone ? zonePt(pose, cue.zone) : null;
  const fxs: React.ReactNode[] = [];
  (cue.fx ?? []).forEach((q, i) => {
    if (q.type === 'arrow') {
      const a = zonePt(pose, q.zone!);
      const fx: Fx = {type: 'arrow', from: [a.x, a.y], to: [a.x + q.d![0], a.y + q.d![1]], curve: q.curve, slow: q.slow};
      fxs.push(<FxOne key={i} fx={fx} t={t} t0={cue.t} t1={cue.e} f={f} />);
    } else if (q.type === 'beam') {
      const a = zonePt(pose, q.zones![0]);
      const b = zonePt(pose, q.zones![1]);
      fxs.push(<FxOne key={i} fx={{type: 'beam', from: [a.x, a.y], to: [b.x, b.y]}} t={t} t0={cue.t} t1={cue.e} f={f} />);
    } else if (q.type === 'mark') {
      const a = zonePt(pose, q.zone!);
      fxs.push(<FxOne key={i} fx={{type: 'mark', kind: q.kind, at: [a.x + (q.off?.[0] ?? 0), a.y + (q.off?.[1] ?? 0)]}} t={t} t0={cue.t} t1={cue.e} f={f} />);
    } else if (q.type === 'line') {
      const pts = q.zones!.map((zz) => zonePt(pose, zz));
      const a = pts[0];
      const b = pts[1];
      const ext = {x: b.x + (b.x - a.x) * 0.25, y: b.y + (b.y - a.y) * 0.25};
      const st = {x: a.x - (b.x - a.x) * 0.15, y: a.y - (b.y - a.y) * 0.15};
      fxs.push(
        <g key={i}>
          <line x1={st.x} y1={st.y} x2={ext.x} y2={ext.y} stroke="#000" strokeOpacity={0.3} strokeWidth={16} strokeLinecap="round" />
          <line x1={st.x} y1={st.y} x2={ext.x} y2={ext.y} stroke="#00e676" strokeWidth={9} strokeDasharray="26 14" strokeDashoffset={-f * 2} strokeLinecap="round" />
        </g>,
      );
    } else if (q.type === 'cross') {
      const a = zonePt(pose, q.zone!);
      const ph = t - cue.t;
      const vert = ph < 2.38;
      const arrows = vert
        ? [
            [0, -1],
            [0, 1],
          ]
        : [
            [-1, 0],
            [1, 0],
          ];
      fxs.push(
        <g key={i}>
          {arrows.map(([dx, dy], j) => (
            <path
              key={j}
              d={`M ${a.x + dx * 60} ${a.y + dy * 60} l ${dx * 60} ${dy * 60} m ${-dx * 22 - dy * 22} ${-dy * 22 - dx * 22} l ${dx * 22 + dy * 22} ${dy * 22 + dx * 22} l ${-dx * 22 + dy * 22} ${-dy * 22 + dx * 22}`}
              stroke="#ffe14d"
              strokeWidth={11}
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={0.55 + 0.45 * pulse}
            />
          ))}
        </g>,
      );
    }
  });
  const tagY = z ? Math.max(z.y - 190, 470) : 0;
  const tagX = z ? clamp(z.x, 170, 910) : 0;
  return (
    <svg viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, width: 1080, height: 1920, opacity: o}}>
      <defs>
        <radialGradient id="mglow2">
          <stop offset="0%" stopColor={col} stopOpacity={0.6} />
          <stop offset="60%" stopColor={col} stopOpacity={0.25} />
          <stop offset="100%" stopColor={col} stopOpacity={0} />
        </radialGradient>
      </defs>
      {z && (
        <g transform={`translate(${z.x} ${z.y}) scale(${s})`}>
          <circle r={115} fill="url(#mglow2)" />
          <circle r={78 + 26 * pulse} fill="none" stroke={col} strokeOpacity={1 - pulse} strokeWidth={6} />
          <circle r={74} fill="none" stroke={col} strokeWidth={9} />
        </g>
      )}
      {fxs}
      {z && cue.tag && (
        <g opacity={ramp(t, cue.t + 0.15, cue.t + 0.4)}>
          <line x1={z.x} y1={z.y - 80} x2={tagX} y2={tagY + 30} stroke="#fff" strokeWidth={5} />
          <g transform={`translate(${tagX} ${tagY})`}>
            <rect x={-(cue.tag.length * 17 + 34)} y={-36} width={cue.tag.length * 34 + 68} height={70} rx={35} fill={col} stroke="#fff" strokeWidth={4} />
            <text y={14} textAnchor="middle" fontFamily={FONT} fontSize={40} fill={C.navy}>
              {cue.tag}
            </text>
          </g>
        </g>
      )}
    </svg>
  );
};

// dây / khăn vòng qua lòng bàn chân
const Strap: React.FC<{pose: Pose; k: number}> = ({pose, k}) => {
  if (k <= 0.01) return null;
  const toe = pol(pose.A, 104, pose.fAng);
  const sole1 = pol(pose.A, 30, pose.fAng);
  const n = pose.fAng + 90;
  const s1 = pol(toe, 26, n);
  const s2 = pol(sole1, 30, n);
  const W = pose.W;
  return (
    <g opacity={k}>
      <path d={`M ${W.x + 20} ${W.y - 6} L ${s1.x} ${s1.y} Q ${lp(s1, s2, 0.5).x + 18} ${lp(s1, s2, 0.5).y} ${s2.x} ${s2.y} L ${W.x + 16} ${W.y + 8}`} stroke="#ff7043" strokeWidth={12} fill="none" strokeLinejoin="round" strokeLinecap="round" />
    </g>
  );
};

const Cheer: React.FC<{t: number}> = ({t}) => {
  const a = 22.38;
  const b = 26.9;
  if (t < a || t > b) return null;
  const o = fadeIO(t, a, b, 0.3);
  return (
    <div style={{position: 'absolute', left: 90, top: 470, width: 900, opacity: o, transform: `scale(${pop(t, a)})`, display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
      <div style={{background: '#ffffff', borderRadius: 34, padding: '18px 40px 24px', boxShadow: '0 12px 34px rgba(0,0,0,0.3)', border: `8px solid ${C.yellow}`, textAlign: 'center'}}>
        <div style={{fontFamily: FONT, fontSize: 96, color: C.red, lineHeight: 1.05}}>CỐ LÊN NÀO!</div>
        <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 44, color: C.navy}}>đã qua hơn nửa chặng đường</div>
        <div style={{display: 'flex', gap: 12, justifyContent: 'center', marginTop: 16}}>
          {Array.from({length: 8}).map((_, i) => {
            const on = i < 5 || (i === 5 && t > 24.84);
            return (
              <div key={i} style={{width: 74, height: 74, borderRadius: 37, background: on ? C.teal : '#e3e8ee', color: on ? '#fff' : '#9aa5b1', fontFamily: FONT, fontSize: 36, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${i === 5 && t > 24.84 ? pop(t, 24.84) : 1})`}}>
                {i + 1}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// phụ đề lời nói đoạn cuối (người thật), chữ sáng dần theo từng từ
const Subtitle: React.FC<{t: number}> = ({t}) => {
  const subs = SUBS as {t: number; e: number; w: [string, number][]}[];
  const cur = [...subs].reverse().find((x) => t >= x.t && t < x.e);
  if (!cur) return null;
  const s = 0.9 + 0.1 * ease(ramp(t, cur.t, cur.t + 0.2));
  return (
    <div style={{position: 'absolute', left: 50, right: 50, top: 1430, display: 'flex', justifyContent: 'center', opacity: ramp(t, cur.t, cur.t + 0.12), transform: `scale(${s})`}}>
      <div style={{background: 'rgba(11,34,54,0.82)', borderRadius: 28, padding: '18px 34px', textAlign: 'center', maxWidth: 960, boxShadow: '0 10px 30px rgba(0,0,0,0.35)'}}>
        {cur.w.map(([w, wt], i) => {
          const on = t >= wt;
          return (
            <span key={i} style={{fontFamily: FONT, fontSize: 64, lineHeight: 1.25, color: on ? (/^[0-9]/.test(w) || w === 'Đức' ? C.yellow : '#ffffff') : 'rgba(255,255,255,0.45)', display: 'inline-block', marginRight: 16, transform: `translateY(${on ? -4 * (1 - ramp(t, wt, wt + 0.15)) : 0}px)`}}>
              {w}
            </span>
          );
        })}
      </div>
    </div>
  );
};

const Rules: React.FC<{t: number}> = ({t}) => {
  const o = ramp(t, END_AT, END_AT + 0.4);
  if (o <= 0) return null;
  return (
    <div style={{position: 'absolute', left: 50, top: 450, width: 980, height: 1060, borderRadius: 40, background: 'rgba(255,255,255,0.97)', boxShadow: '0 16px 40px rgba(0,0,0,0.3)', opacity: o, transform: `scale(${lerp(0.9, 1, ease(o))})`, padding: '40px 50px', boxSizing: 'border-box'}}>
      <div style={{fontFamily: FONT, fontSize: 64, color: C.navy, textAlign: 'center', marginBottom: 26}}>
        HÃY NHỚ GIÚP <span style={{color: C.teal}}>ĐỨC</span>
      </div>
      {RULES.map((r, i) => {
        const k = ramp(t, r.t, r.t + 0.3);
        return (
          <div key={i} style={{display: 'flex', alignItems: 'center', gap: 26, height: 142, opacity: k, transform: `translateX(${(1 - ease(k)) * -80}px)`}}>
            <svg viewBox="-60 -60 120 120" style={{width: 100, height: 100, flex: 'none'}}>
              <Check x={0} y={0} ok={!r.bad} s={1.6 * pop(t, r.t)} />
            </svg>
            <div style={{fontFamily: FONT, fontSize: 52, color: r.bad ? C.red : C.navy, lineHeight: 1.1}}>{r.text}</div>
          </div>
        );
      })}
    </div>
  );
};

export const Lung02: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const {pose, strap} = poseAt(t);
  const cam = camOf(t);
  CAM = cam;
  const ex = [...EXS].reverse().find((e) => t >= e.start);
  const cue = CUES.find((c) => t >= c.t && t < c.e);
  // đổi tư thế giữa 2 động tác: mờ dần qua lại
  const swap = t >= 26.7 && t < 27.6 ? Math.abs((t - 27.15) / 0.45) : 1;
  const isEnd = t >= END_AT;
  const text = cue ? cue.text : ex ? ex.idle : '';
  const F0 = Math.round((END_AT - 0.5) * FPS);
  const cover = 1 - ramp(t, END_AT, END_AT + 0.5); // đoạn cuối không có động tác → hiện lại người thật
  return (
    <AbsoluteFill style={{backgroundColor: '#f1ece5'}}>
      <Sequence from={F0}>
        <OffthreadVideo src={staticFile('lung02.mp4')} startFrom={F0} muted />
      </Sequence>
      {cover > 0 && (
      <AbsoluteFill style={{opacity: cover}}>
      <svg viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, width: 1080, height: 1920}}>
        <defs>
          <linearGradient id="gWall" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f7f4ef" />
            <stop offset="100%" stopColor="#e6dfd6" />
          </linearGradient>
          <linearGradient id="gShine" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#fff" stopOpacity={0} />
            <stop offset="50%" stopColor="#fff" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#fff" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gBed" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f2f0f8" />
            <stop offset="100%" stopColor="#d9d5e6" />
          </linearGradient>
          <linearGradient id="gCoat" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="100%" stopColor="#dde4ec" />
          </linearGradient>
          <linearGradient id="gPants" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#efe2c8" />
            <stop offset="100%" stopColor="#cdb791" />
          </linearGradient>
          <radialGradient id="gSkin" cx="0.65" cy="0.35" r="0.8">
            <stop offset="0%" stopColor={C.skinL} />
            <stop offset="100%" stopColor={C.skin} />
          </radialGradient>
          <filter id="blur8">
            <feGaussianBlur stdDeviation="8" />
          </filter>
        </defs>
        <Room />
        <g opacity={swap} transform={`translate(${540 + cam.dx} ${BED}) scale(${cam.k}) translate(-540 ${-BED})`}>
          <NguoiTap p={pose} />
          <Strap pose={pose} k={strap} />
        </g>
      </svg>
      {!isEnd && <BodyLayer t={t} f={f} pose={pose} cue={cue} />}
      <Cheer t={t} />
      </AbsoluteFill>
      )}
      <Subtitle t={t} />
      <TitleBar />
      {ex && !isEnd && <Chip pill={`ĐỘNG TÁC ${ex.n}`} name={ex.name} info={ex.info} t={t} t0={ex.start} t1={ex.end} />}
      {!isEnd && <Panel t={t} text={text} cue={cue} key0={cue ? cue.t : ex ? ex.start : 0} />}
    </AbsoluteFill>
  );
};
