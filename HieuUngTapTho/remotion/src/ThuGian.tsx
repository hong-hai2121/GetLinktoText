import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';

// Video "Thư giãn cơ tiến triển - edit (2).mp4": 1080x1920, 30 fps, 334 s.
// Đoạn 48.52 s -> 311.56 s (nói về động tác) được phủ KÍN cả khung bằng hình minh họa.
// Mốc giờ lấy từ Whisper (word timestamps).

export const FPS = 30;
export const COVER_IN = 48.52;
export const COVER_OUT = 311.56;

const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ramp = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
const ease = (x: number) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const sm = (t: number, a: number, b: number) => ease(ramp(t, a, b));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;

const FONT = "'Segoe UI Black', 'Segoe UI', sans-serif";
const FONT_B = "'Segoe UI', sans-serif";
const C = {
  bg1: '#0a1a2b',
  bg2: '#123a55',
  skin: '#f3c79b',
  skinD: '#d99f6f',
  hair: '#2a2018',
  shirt: '#3f8efc',
  shirtD: '#2a64c4',
  pants: '#34495e',
  pantsD: '#2c3e50',
  red: '#ff4d4d',
  warm: '#ffb547',
  teal: '#35d0c8',
  yellow: '#ffd54a',
  white: '#ffffff',
};

type Phase = 'intro' | 'inhale' | 'hold' | 'release' | 'rest' | 'cheer';
type Ev = [number, Phase];
type Scene = 'hands' | 'arms' | 'shoulders' | 'brow' | 'eyes' | 'jaw' | 'belly' | 'glute' | 'thigh' | 'foot';
interface Group {
  n: number;
  name: string;
  start: number;
  end: number;
  scene: Scene;
  cycles: [number, number][]; // [bắt đầu gồng, thở ra]
  ev: Ev[];
  tense: string;
  relax: string;
  rest: string;
}

const NANG_AM_MEM = 'Nặng dần · ấm dần · mềm dần';

const GROUPS: Group[] = [
  {
    n: 1, name: 'BÀN TAY', start: 79.14, end: 113.5, scene: 'hands',
    cycles: [[83.92, 89.53], [93.89, 103.41]],
    ev: [[79.14, 'intro'], [82.12, 'inhale'], [84.8, 'hold'], [89.53, 'release'], [92.11, 'inhale'], [98.2, 'hold'], [103.41, 'release'], [105.37, 'rest']],
    tense: 'Nắm thật chặt 2 bàn tay', relax: 'Buông lỏng hoàn toàn', rest: 'Hơi ấm lan trong lòng bàn tay',
  },
  {
    n: 2, name: 'CÁNH TAY', start: 113.5, end: 133.23, scene: 'arms',
    cycles: [[116.9, 127.69]],
    ev: [[113.5, 'intro'], [116.62, 'inhale'], [120.94, 'hold'], [127.69, 'release'], [130.37, 'rest']],
    tense: 'Gập khuỷu tay, gồng chặt bắp tay', relax: 'Buông thõng cánh tay xuống', rest: NANG_AM_MEM,
  },
  {
    n: 3, name: 'VAI', start: 133.23, end: 155.26, scene: 'shoulders',
    cycles: [[137.73, 147.28]],
    ev: [[133.23, 'intro'], [136.29, 'inhale'], [140.79, 'hold'], [147.28, 'release'], [151.5, 'rest']],
    tense: 'Nhún 2 vai lên thật sát tai', relax: 'Để vai rơi xuống thật nặng', rest: NANG_AM_MEM,
  },
  {
    n: 4, name: 'VẦNG TRÁN', start: 155.26, end: 178.0, scene: 'brow',
    cycles: [[158.92, 168.18]],
    ev: [[155.26, 'intro'], [157.76, 'inhale'], [161.22, 'hold'], [168.18, 'release'], [171.66, 'rest']],
    tense: 'Nhướn mày thật cao', relax: 'Để vầng trán giãn phẳng ra', rest: 'Thả lỏng đôi mắt, chìm dần xuống',
  },
  {
    n: 5, name: 'MẮT', start: 178.0, end: 199.52, scene: 'eyes',
    cycles: [[181.6, 189.44]],
    ev: [[178.0, 'intro'], [181.14, 'inhale'], [185.06, 'hold'], [189.44, 'release'], [193.12, 'rest']],
    tense: 'Nhắm thật chặt 2 mắt', relax: 'Mắt khép hờ, nhẹ bẫng', rest: NANG_AM_MEM,
  },
  {
    n: 6, name: 'CƠ HÀM', start: 199.52, end: 222.52, scene: 'jaw',
    cycles: [[202.3, 213.74]],
    ev: [[199.52, 'intro'], [201.62, 'inhale'], [204.62, 'hold'], [213.74, 'release'], [219.26, 'rest']],
    tense: 'Mím môi, cắn răng vừa phải', relax: 'Hàm hơi hé, lưỡi buông mềm', rest: 'Giữ nguyên tư thế thả lỏng',
  },
  {
    n: 7, name: 'NGỰC & BỤNG', start: 222.52, end: 243.23, scene: 'belly',
    cycles: [[226.1, 236.93]],
    ev: [[222.52, 'intro'], [224.62, 'inhale'], [227.4, 'hold'], [236.93, 'release'], [239.81, 'rest']],
    tense: 'Hít thật sâu, gồng chặt bụng', relax: 'Để bụng xẹp xuống', rest: NANG_AM_MEM,
  },
  {
    n: 8, name: 'CƠ MÔNG', start: 243.23, end: 263.47, scene: 'glute',
    cycles: [[247.07, 256.97]],
    ev: [[243.23, 'intro'], [245.51, 'inhale'], [248.93, 'hold'], [256.97, 'release'], [261.37, 'rest']],
    tense: 'Siết chặt 2 bên mông', relax: 'Buông lỏng cơ mông xuống', rest: NANG_AM_MEM,
  },
  {
    n: 9, name: 'ĐÙI', start: 263.47, end: 284.44, scene: 'thigh',
    cycles: [[266.45, 275.9]],
    ev: [[263.47, 'intro'], [265.41, 'inhale'], [269.61, 'hold'], [275.9, 'release'], [278.86, 'rest'], [282.52, 'cheer']],
    tense: 'Duỗi thẳng chân, gồng chặt đùi', relax: 'Để đôi chân nặng phịch xuống', rest: NANG_AM_MEM,
  },
  {
    n: 10, name: 'BÀN CHÂN', start: 284.44, end: 301.48, scene: 'foot',
    cycles: [[289.3, 297.36]],
    ev: [[284.44, 'intro'], [289.02, 'inhale'], [291.8, 'hold'], [297.36, 'release'], [299.96, 'rest']],
    tense: 'Kéo mũi chân về phía mặt', relax: 'Để cả bàn chân buông thẳng', rest: NANG_AM_MEM,
  },
];

const tensionOf = (t: number, cycles: [number, number][]) =>
  Math.max(0, ...cycles.map(([a, b]) => sm(t, a, a + 0.8) * (1 - sm(t, b, b + 1.1))));

const phaseOf = (t: number, ev: Ev[]) => {
  let i = 0;
  ev.forEach((e, k) => {
    if (t >= e[0]) i = k;
  });
  const next = ev[i + 1] ? ev[i + 1][0] : null;
  return {ph: ev[i][1], t0: ev[i][0], t1: next};
};

// ===================== GLOW =====================
type Glow = {x: number; y: number; rx: number; ry: number};

const Glows: React.FC<{g: Glow[]; red: number; warm: number; f: number; id: string}> = ({g, red, warm, f, id}) => {
  const pulse = 0.72 + 0.28 * Math.sin(f / 3.2);
  const wave = (f % 60) / 60;
  return (
    <g>
      <defs>
        <radialGradient id={`r${id}`}>
          <stop offset="0%" stopColor={C.red} stopOpacity={0.85} />
          <stop offset="60%" stopColor={C.red} stopOpacity={0.35} />
          <stop offset="100%" stopColor={C.red} stopOpacity={0} />
        </radialGradient>
        <radialGradient id={`w${id}`}>
          <stop offset="0%" stopColor={C.warm} stopOpacity={0.75} />
          <stop offset="65%" stopColor={C.warm} stopOpacity={0.25} />
          <stop offset="100%" stopColor={C.warm} stopOpacity={0} />
        </radialGradient>
      </defs>
      {g.map((e, i) => (
        <g key={i}>
          {red > 0.01 && (
            <ellipse cx={e.x} cy={e.y} rx={e.rx * 1.25} ry={e.ry * 1.25} fill={`url(#r${id})`} opacity={red * pulse} />
          )}
          {warm > 0.01 && (
            <g opacity={warm}>
              <ellipse cx={e.x} cy={e.y} rx={e.rx * 1.3} ry={e.ry * 1.3} fill={`url(#w${id})`} />
              <ellipse
                cx={e.x}
                cy={e.y}
                rx={e.rx * (0.9 + 0.9 * wave)}
                ry={e.ry * (0.9 + 0.9 * wave)}
                fill="none"
                stroke={C.warm}
                strokeWidth={5}
                opacity={0.7 * (1 - wave)}
              />
            </g>
          )}
        </g>
      ))}
    </g>
  );
};

const L = (x1: number, y1: number, x2: number, y2: number, c: string, w: number) => (
  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={c} strokeWidth={w} strokeLinecap="round" />
);

// ===================== NGƯỜI NHÌN THẲNG (ngồi, nửa người trên) =====================
type FB = {
  s?: number; // nhún vai
  flex?: number; // gập khuỷu
  fist?: number;
  brow?: number;
  sq?: number; // nhắm chặt mắt
  closed?: number; // nhắm hờ
  jaw?: number; // mím môi cắn răng
  jawOpen?: number;
  belly?: number;
  breath?: number;
};

const frontGeom = (p: FB) => {
  const s = p.s ?? 0;
  const bw = 1 + 0.07 * (p.breath ?? 0);
  const H = {x: 500, y: 270};
  const sh = 72 * s;
  const SL = {x: 500 - 175 * bw, y: 480 - sh};
  const SR = {x: 500 + 175 * bw, y: 480 - sh};
  const arm = (side: -1 | 1) => {
    const S = side < 0 ? SL : SR;
    const J = {x: S.x + side * 8, y: S.y + 45};
    const E = {x: J.x + side * 34, y: J.y + 255};
    const fl = p.flex ?? 0;
    const Hd = {
      x: lerp(E.x + side * 4, J.x - side * 30, fl),
      y: lerp(E.y + 240, J.y + 70, fl),
    };
    return {J, E, Hd};
  };
  return {H, SL, SR, bw, aL: arm(-1), aR: arm(1)};
};

const Hand: React.FC<{x: number; y: number; fist: number; r?: number}> = ({x, y, fist, r = 46}) => (
  <g>
    <circle cx={x} cy={y} r={r} fill={C.skin} stroke={C.skinD} strokeWidth={4} />
    {fist > 0.3 &&
      [-1, 0, 1].map((k) => (
        <path
          key={k}
          d={`M ${x + k * 18 - 7} ${y - 16} Q ${x + k * 18} ${y - 26} ${x + k * 18 + 7} ${y - 16}`}
          stroke={C.skinD}
          strokeWidth={4}
          fill="none"
          opacity={(fist - 0.3) / 0.7}
        />
      ))}
  </g>
);

const FrontBody: React.FC<FB & {focus: string; red: number; warm: number; f: number}> = (p) => {
  const {H, SL, SR, bw, aL, aR} = frontGeom(p);
  const fist = p.fist ?? 0;
  const flex = p.flex ?? 0;
  const brow = p.brow ?? 0;
  const sq = p.sq ?? 0;
  const closed = p.closed ?? 0;
  const jaw = p.jaw ?? 0;
  const jawOpen = p.jawOpen ?? 0;
  const belly = p.belly ?? 0;

  const torso = `M 452 425 Q ${SL.x + 50} ${SL.y - 22} ${SL.x} ${SL.y + 6} Q ${SL.x - 38} ${SL.y + 34} ${SL.x - 32} ${SL.y + 130}
    L ${500 - 205 * bw} 1130 L ${500 + 205 * bw} 1130 L ${SR.x + 32} ${SR.y + 130} Q ${SR.x + 38} ${SR.y + 34} ${SR.x} ${SR.y + 6}
    Q ${SR.x - 50} ${SR.y - 22} 548 425 Z`;

  const upper = (a: {J: {x: number; y: number}; E: {x: number; y: number}}, side: number) => {
    const mid = {x: lerp(a.J.x, a.E.x, 0.55), y: lerp(a.J.y, a.E.y, 0.55)};
    const bulge = flex * (0.4 + 0.6 * p.red);
    return (
      <g>
        {L(a.J.x, a.J.y, a.E.x, a.E.y, C.skin, 80)}
        <ellipse cx={mid.x - side * 6} cy={mid.y} rx={40 + 26 * bulge} ry={74} fill={C.skin} />
        {L(a.J.x, a.J.y, lerp(a.J.x, a.E.x, 0.32), lerp(a.J.y, a.E.y, 0.32), C.shirt, 98)}
      </g>
    );
  };

  // Mắt
  const eye = (cx: number) => {
    const y = H.y - 4;
    const o = clamp(1 - Math.max(sq, closed) * 1.15);
    if (o > 0.12) {
      return (
        <g>
          <ellipse cx={cx} cy={y} rx={27} ry={17 * o} fill="white" />
          <circle cx={cx} cy={y} r={Math.min(11, 16 * o)} fill="#3b2a1e" />
          <path d={`M ${cx - 29} ${y - 2} Q ${cx} ${y - 22 * o - 4} ${cx + 29} ${y - 2}`} stroke="#3b2a1e" strokeWidth={5} fill="none" />
        </g>
      );
    }
    if (sq >= closed) {
      const out = cx < 500 ? -1 : 1;
      return (
        <g stroke="#3b2a1e" strokeWidth={6} fill="none" strokeLinecap="round">
          <path d={`M ${cx - 30} ${y + 2} Q ${cx} ${y + 12} ${cx + 30} ${y + 2}`} />
          <path d={`M ${cx - 26} ${y - 6} Q ${cx} ${y + 4} ${cx + 26} ${y - 6}`} />
          {[-12, 0, 12].map((k) => (
            <line key={k} x1={cx + out * 36} y1={y + k * 0.8} x2={cx + out * 52} y2={y + k * 1.6} opacity={sq} />
          ))}
        </g>
      );
    }
    return <path d={`M ${cx - 27} ${y} Q ${cx} ${y + 13} ${cx + 27} ${y}`} stroke="#3b2a1e" strokeWidth={6} fill="none" strokeLinecap="round" />;
  };

  const raise = 34 * brow - 12 * sq;
  const browP = (cx: number) => (
    <path
      d={`M ${cx - 34} ${H.y - 40 - raise} Q ${cx} ${H.y - 56 - raise - 10 * brow} ${cx + 34} ${H.y - 40 - raise}`}
      stroke={C.hair}
      strokeWidth={11}
      fill="none"
      strokeLinecap="round"
    />
  );

  const mouthY = H.y + 92;
  const smileCtl = lerp(16, -2, jaw);

  const glows: Record<string, Glow[]> = {
    hands: [
      {x: aL.Hd.x, y: aL.Hd.y, rx: 80, ry: 80},
      {x: aR.Hd.x, y: aR.Hd.y, rx: 80, ry: 80},
    ],
    arms: [
      {x: lerp(aL.J.x, aL.E.x, 0.55), y: lerp(aL.J.y, aL.E.y, 0.55), rx: 80, ry: 120},
      {x: lerp(aR.J.x, aR.E.x, 0.55), y: lerp(aR.J.y, aR.E.y, 0.55), rx: 80, ry: 120},
    ],
    shoulders: [
      {x: SL.x + 40, y: SL.y - 5, rx: 120, ry: 80},
      {x: SR.x - 40, y: SR.y - 5, rx: 120, ry: 80},
    ],
    brow: [{x: H.x, y: H.y - 72, rx: 125, ry: 48}],
    eyes: [
      {x: H.x - 48, y: H.y - 4, rx: 55, ry: 40},
      {x: H.x + 48, y: H.y - 4, rx: 55, ry: 40},
    ],
    jaw: [
      {x: H.x - 92, y: H.y + 78, rx: 42, ry: 60},
      {x: H.x + 92, y: H.y + 78, rx: 42, ry: 60},
      {x: H.x, y: mouthY, rx: 60, ry: 28},
    ],
    belly: [{x: 500, y: 810, rx: 185, ry: 210}],
    all: [],
  };

  return (
    <g>
      {/* cổ */}
      {L(500, 360, 500, 470 - 40 * (p.s ?? 0), C.skin, 96)}
      {/* thân */}
      <path d={torso} fill={C.shirt} />
      <path d={`M 452 425 Q 500 470 548 425`} stroke={C.shirtD} strokeWidth={8} fill="none" />
      {/* bụng gồng: các múi */}
      {belly > 0.02 && (
        <g opacity={belly} stroke={C.shirtD} strokeWidth={7} fill="none" strokeLinecap="round">
          {[720, 800, 880].map((y) => (
            <g key={y}>
              <path d={`M 430 ${y} Q 465 ${y + 14} 492 ${y}`} />
              <path d={`M 508 ${y} Q 535 ${y + 14} 570 ${y}`} />
            </g>
          ))}
          <line x1={500} y1={690} x2={500} y2={940} />
        </g>
      )}
      {/* tay */}
      {upper(aL, -1)}
      {upper(aR, 1)}
      {L(aL.E.x, aL.E.y, aL.Hd.x, aL.Hd.y, C.skin, 66)}
      {L(aR.E.x, aR.E.y, aR.Hd.x, aR.Hd.y, C.skin, 66)}
      <Hand x={aL.Hd.x} y={aL.Hd.y} fist={fist} />
      <Hand x={aR.Hd.x} y={aR.Hd.y} fist={fist} />

      {/* đầu */}
      <ellipse cx={H.x - 114} cy={H.y + 12} rx={22} ry={36} fill={C.skin} />
      <ellipse cx={H.x + 114} cy={H.y + 12} rx={22} ry={36} fill={C.skin} />
      <ellipse cx={H.x} cy={H.y} rx={114} ry={142} fill={C.skin} />
      <path
        d={`M ${H.x - 120} ${H.y + 4} C ${H.x - 132} ${H.y - 170} ${H.x + 132} ${H.y - 170} ${H.x + 120} ${H.y + 4}
           C ${H.x + 108} ${H.y - 70} ${H.x + 50} ${H.y - 108} ${H.x - 4} ${H.y - 98}
           C ${H.x - 60} ${H.y - 106} ${H.x - 108} ${H.y - 70} ${H.x - 120} ${H.y + 4} Z`}
        fill={C.hair}
      />
      {/* nếp nhăn trán */}
      {brow > 0.02 &&
        [-86, -73, -60].map((dy, i) => (
          <path
            key={dy}
            d={`M ${H.x - 62 + i * 6} ${H.y + dy} Q ${H.x} ${H.y + dy - 9} ${H.x + 62 - i * 6} ${H.y + dy}`}
            stroke={C.skinD}
            strokeWidth={5}
            fill="none"
            opacity={brow}
          />
        ))}
      {browP(H.x - 48)}
      {browP(H.x + 48)}
      {eye(H.x - 48)}
      {eye(H.x + 48)}
      <path d={`M ${H.x - 6} ${H.y + 8} Q ${H.x - 24} ${H.y + 56} ${H.x - 4} ${H.y + 60} Q ${H.x + 10} ${H.y + 64} ${H.x + 20} ${H.y + 56}`} stroke={C.skinD} strokeWidth={6} fill="none" strokeLinecap="round" />
      {/* miệng */}
      {jawOpen > 0.05 ? (
        <ellipse cx={H.x} cy={mouthY + 4} rx={22} ry={4 + 12 * jawOpen} fill="#7a3428" />
      ) : (
        <path
          d={`M ${H.x - 40 - 6 * jaw} ${mouthY} Q ${H.x} ${mouthY + smileCtl} ${H.x + 40 + 6 * jaw} ${mouthY}`}
          stroke="#a0523d"
          strokeWidth={8 + 3 * jaw}
          fill="none"
          strokeLinecap="round"
        />
      )}
      {/* cơ hàm nổi khi cắn răng */}
      {jaw > 0.05 &&
        [-1, 1].map((k) => (
          <path
            key={k}
            d={`M ${H.x + k * 82} ${H.y + 50} Q ${H.x + k * 100} ${H.y + 82} ${H.x + k * 80} ${H.y + 112}`}
            stroke={C.skinD}
            strokeWidth={6}
            fill="none"
            opacity={jaw}
          />
        ))}

      <Glows g={glows[p.focus] ?? []} red={p.red} warm={p.warm} f={p.f} id={`fb${p.focus}`} />
    </g>
  );
};

// ===================== HAI BÀN TAY CẬN CẢNH =====================
const BigHand: React.FC<{cx: number; cy: number; fist: number; mirror: boolean; jit: number}> = ({cx, cy, fist, mirror, jit}) => {
  const fx = [-78, -26, 26, 78];
  const len = [150, 180, 168, 128];
  const k = 1 - 0.72 * fist;
  const thumbA = lerp(-35, 15, fist); // độ, so với phương ngang hướng vào trong
  const tr = `translate(${cx + jit} ${cy}) scale(${mirror ? -1 : 1} 1)`;
  const ta = (thumbA * Math.PI) / 180;
  return (
    <g transform={tr}>
      {/* cổ tay */}
      <rect x={-88} y={150} width={176} height={260} rx={60} fill={C.skin} />
      <rect x={-104} y={300} width={208} height={140} rx={30} fill={C.shirt} />
      {/* ngón */}
      {fx.map((x, i) => (
        <line key={i} x1={x} y1={-40} x2={x + (i - 1.5) * 10 * k} y2={-40 - len[i] * k} stroke={C.skin} strokeWidth={54} strokeLinecap="round" />
      ))}
      {/* lòng bàn tay */}
      <rect x={-118} y={-70} width={236} height={250} rx={80} fill={C.skin} />
      {/* ngón gập (nắm đấm) */}
      {fist > 0.25 && (
        <g opacity={clamp((fist - 0.25) / 0.5)}>
          <rect x={-112} y={-62} width={224} height={110} rx={50} fill={C.skin} stroke={C.skinD} strokeWidth={5} />
          {[-56, 0, 56].map((x) => (
            <line key={x} x1={x} y1={-56} x2={x} y2={40} stroke={C.skinD} strokeWidth={5} />
          ))}
        </g>
      )}
      {/* ngón cái */}
      <line
        x1={lerp(108, 96, fist)}
        y1={lerp(100, 58, fist)}
        x2={lerp(196, -20, fist)}
        y2={lerp(-8, 24, fist)}
        stroke={C.skin}
        strokeWidth={56}
        strokeLinecap="round"
      />
      {fist > 0.5 && <path d="M -10 6 Q 0 -6 14 6" stroke={C.skinD} strokeWidth={4} fill="none" />}
      {/* khớp đốt */}
      {[-78, -26, 26, 78].map((x) => (
        <path key={x} d={`M ${x - 14} ${-30} Q ${x} ${-40} ${x + 14} ${-30}`} stroke={C.skinD} strokeWidth={4} fill="none" opacity={0.6} />
      ))}
    </g>
  );
};

// ===================== NGƯỜI NẰM NGỬA (nhìn nghiêng) =====================
type LB = {glute?: number; thigh?: number; foot?: number; breath?: number; sit?: number; wiggle?: number; f: number; red: number; warm: number; focus: string};

const LyingBody: React.FC<LB> = (p) => {
  const glute = p.glute ?? 0;
  const thigh = p.thigh ?? 0;
  const foot = p.foot ?? 0;
  const br = p.breath ?? 0;
  const sit = p.sit ?? 0;
  const wig = p.wiggle ?? 0;
  const HIP = {x: 540, y: 575};
  const A = {x: 915, y: 588};
  const fdeg = lerp(-52, -102, foot) + wig * 8 * Math.sin(p.f / 2.5);
  const fa = (fdeg * Math.PI) / 180;
  const toe = {x: A.x + Math.cos(fa) * 118, y: A.y + Math.sin(fa) * 118};
  const glows: Record<string, Glow[]> = {
    glute: [{x: 548, y: 612, rx: 95, ry: 55}],
    thigh: [{x: 660, y: 560, rx: 140, ry: 55}],
    foot: [
      {x: (A.x + toe.x) / 2, y: (A.y + toe.y) / 2, rx: 75, ry: 75},
      {x: 830, y: 600, rx: 80, ry: 40},
    ],
    all: [
      {x: 150, y: 545, rx: 85, ry: 85},
      {x: 360, y: 560, rx: 160, ry: 80},
      {x: 640, y: 580, rx: 150, ry: 60},
      {x: 880, y: 575, rx: 110, ry: 60},
    ],
  };
  const sq = 1 - 0.28 * glute;
  return (
    <g>
      {/* giường */}
      <rect x={40} y={700} width={40} height={130} rx={10} fill="#5d4037" />
      <rect x={930} y={700} width={40} height={130} rx={10} fill="#5d4037" />
      <rect x={30} y={690} width={950} height={40} rx={14} fill="#6d4c41" />
      <rect x={30} y={615} width={950} height={85} rx={30} fill="#dfe6ee" />
      <ellipse cx={135} cy={605} rx={110} ry={34} fill="#ffffff" />

      {/* chân */}
      {L(560, 578, 760, 586, C.pants, 104)}
      {L(760, 586, 905, 592, C.pants, 70)}
      {/* cơ đùi gồng */}
      {thigh > 0.02 && (
        <g opacity={thigh} stroke={C.pantsD} strokeWidth={6} fill="none" strokeLinecap="round">
          <path d="M 600 548 Q 660 530 730 548" />
          <path d="M 620 566 Q 670 552 720 566" />
        </g>
      )}
      {/* bàn chân */}
      <g transform={`translate(${A.x} ${A.y}) rotate(${fdeg})`}>
        <path
          d="M -30 6 Q -36 34 -6 38 L 104 26 Q 134 22 132 4 Q 130 -14 112 -16 L 46 -26 Q 14 -30 -6 -30 Q -32 -26 -30 6 Z"
          fill={C.skin}
          stroke={C.skinD}
          strokeWidth={4}
        />
        {[0, 1, 2].map((i) => (
          <line key={i} x1={112 - i * 2} y1={-10 + i * 10} x2={128 - i * 3} y2={-8 + i * 10} stroke={C.skinD} strokeWidth={3} />
        ))}
      </g>

      {/* mông + hông */}
      <ellipse cx={540} cy={580} rx={98} ry={64} fill={C.pants} />
      <ellipse cx={548} cy={612} rx={72 * (2 - sq) * 0.95} ry={30 * sq} fill={C.pantsD} />
      {glute > 0.05 &&
        [-1, 1].map((k) => (
          <g key={k} opacity={glute} transform={`translate(${548 + k * 150} 612) scale(${-k} 1)`}>
            <path d="M -40 0 L 0 0 M -16 -16 L 0 0 L -16 16" stroke={C.yellow} strokeWidth={9} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </g>
        ))}

      {/* phần trên (xoay quanh hông khi ngồi dậy) */}
      <g transform={`rotate(${sit * 68} ${HIP.x} ${HIP.y})`}>
        {L(250, 570, 520, 575, C.shirt, 128)}
        <ellipse cx={340} cy={548 - 6 * br} rx={110} ry={58 + 8 * br} fill={C.shirt} />
        {L(185, 562, 245, 566, C.skin, 54)}
        <circle cx={128} cy={560} r={66} fill={C.hair} />
        <circle cx={146} cy={548} r={58} fill={C.skin} />
        <circle cx={182} cy={500} r={13} fill={C.skin} />
        <path d="M 156 512 Q 168 521 182 513" stroke="#3b2a1e" strokeWidth={5} fill="none" strokeLinecap="round" />
        <ellipse cx={126} cy={565} rx={14} ry={20} fill={C.skinD} />
        {/* tay */}
        {L(265, 556, 300, 566, C.shirt, 58)}
        {L(290, 566, 410, 588, C.skin, 44)}
        {L(410, 588, 515, 594, C.skin, 40)}
        <circle cx={522 + wig * 5 * Math.sin(p.f / 2)} cy={595} r={27} fill={C.skin} />
      </g>

      <Glows g={glows[p.focus] ?? []} red={p.red} warm={p.warm} f={p.f} id={`lb${p.focus}`} />
    </g>
  );
};

// ===================== GHẾ TỰA (hình nhỏ cho phần chuẩn bị) =====================
const ChairPerson: React.FC = () => (
  <g>
    <path d="M 60 40 L 110 230 L 260 230 L 270 300" stroke="#8d6e63" strokeWidth={20} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    {L(120, 230, 110, 320, '#6d4c41', 14)}
    {L(255, 230, 265, 320, '#6d4c41', 14)}
    <circle cx={82} cy={58} r={34} fill={C.skin} />
    {L(92, 100, 128, 205, C.shirt, 54)}
    {L(130, 208, 240, 205, C.pants, 44)}
    {L(240, 205, 262, 300, C.pants, 36)}
  </g>
);

// ===================== KHUNG CHỮ =====================
const Header: React.FC<{pill: string; title: string; n?: number}> = ({pill, title, n}) => (
  <div style={{position: 'absolute', top: 90, left: 0, right: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18}}>
    <div style={{background: C.yellow, color: '#1a1a1a', fontFamily: FONT, fontSize: 44, padding: '8px 30px', borderRadius: 18}}>{pill}</div>
    <div
      style={{
        color: 'white',
        fontFamily: FONT,
        fontSize: title.length > 12 ? 96 : 118,
        lineHeight: 1.05,
        textAlign: 'center',
        textShadow: '0 6px 24px rgba(0,0,0,0.5)',
        padding: '0 40px',
      }}
    >
      {title}
    </div>
    {n ? (
      <div style={{display: 'flex', gap: 10, marginTop: 4}}>
        {Array.from({length: 10}, (_, i) => (
          <div
            key={i}
            style={{
              width: 64,
              height: 14,
              borderRadius: 7,
              background: i + 1 < n ? C.teal : i + 1 === n ? C.yellow : 'rgba(255,255,255,0.18)',
            }}
          />
        ))}
      </div>
    ) : null}
  </div>
);

const Ring: React.FC<{k: number; color: string; text: string; size?: number; font?: number}> = ({k, color, text, size = 210, font = 96}) => {
  const r = size / 2 - 14;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.15)" strokeWidth={16} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={16}
        strokeLinecap="round"
        strokeDasharray={`${c * clamp(k)} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x={size / 2} y={size / 2 + font * 0.36} textAnchor="middle" fontFamily={FONT} fontSize={font} fill="white">
        {text}
      </text>
    </svg>
  );
};

const Panel: React.FC<{label: string; sub: string; color: string; ring?: React.ReactNode; pop: number}> = ({label, sub, color, ring, pop}) => (
  <div
    style={{
      position: 'absolute',
      left: 40,
      right: 40,
      top: 1460,
      height: 380,
      borderRadius: 44,
      background: 'rgba(255,255,255,0.08)',
      border: `5px solid ${color}`,
      display: 'flex',
      alignItems: 'center',
      padding: '0 44px',
      gap: 30,
      boxShadow: `0 0 60px ${color}44`,
    }}
  >
    <div style={{flex: 1, transform: `scale(${0.9 + 0.1 * pop})`, transformOrigin: 'left center', opacity: 0.3 + 0.7 * pop}}>
      <div style={{color, fontFamily: FONT, fontSize: label.length > 18 ? 66 : 78, lineHeight: 1.08}}>{label}</div>
      <div style={{color: 'white', fontFamily: FONT_B, fontWeight: 700, fontSize: 50, marginTop: 14, lineHeight: 1.15}}>{sub}</div>
    </div>
    {ring}
  </div>
);

const Stage: React.FC<{viewBox: string; children: React.ReactNode}> = ({viewBox, children}) => (
  <svg
    width={1000}
    height={1000}
    viewBox={viewBox}
    style={{position: 'absolute', left: 40, top: 430}}
    preserveAspectRatio="xMidYMid meet"
  >
    {children}
  </svg>
);

// ===================== CẢNH TỪNG NHÓM =====================
const GroupScene: React.FC<{g: Group; t: number; f: number}> = ({g, t, f}) => {
  const tens = tensionOf(t, g.cycles);
  const {ph, t0, t1} = phaseOf(t, g.ev);
  const lastRel = Math.max(...g.ev.filter((e) => e[1] === 'release' && e[0] <= t).map((e) => e[0]), -1);
  const relaxed = lastRel > 0 && tens < 0.5;
  const warm = relaxed ? sm(t, lastRel + 0.6, lastRel + 2.2) * (0.75 + 0.25 * Math.sin(f / 9)) : 0;
  const red = tens;
  const pop = sm(t, t0, t0 + 0.35);

  let label = '';
  let sub = '';
  let color = C.white;
  let ring: React.ReactNode = null;
  if (ph === 'intro') {
    label = `NHÓM ${g.n}: ${g.name}`;
    sub = g.tense;
    color = C.yellow;
  } else if (ph === 'inhale') {
    label = 'HÍT VÀO · GỒNG CHẶT';
    sub = g.tense;
    color = '#ff8a65';
  } else if (ph === 'hold') {
    label = 'GIỮ 5 GIÂY';
    sub = g.tense;
    color = C.red;
    const dur = (t1 ?? t0 + 5) - t0;
    const k = ramp(t, t0, t0 + dur);
    const num = clamp(5 - Math.floor(k * 5), 1, 5);
    ring = <Ring k={1 - k} color={C.red} text={`${num}`} />;
  } else if (ph === 'release') {
    label = 'THỞ RA · BUÔNG LỎNG';
    sub = g.relax;
    color = C.teal;
  } else if (ph === 'rest') {
    label = 'THẢ LỎNG 10–20 GIÂY';
    sub = g.rest;
    color = C.warm;
    const end = t1 ?? g.end;
    ring = <Ring k={ramp(t, t0, end)} color={C.warm} text="~" font={110} />;
  } else if (ph === 'cheer') {
    label = 'CỐ LÊN!';
    sub = 'Sắp hoàn thành rồi';
    color = C.yellow;
  }

  let art: React.ReactNode = null;
  let vb = '0 60 1000 1000';
  const jit = red > 0.5 ? Math.sin(f * 2.1) * 2.5 * red : 0;
  switch (g.scene) {
    case 'hands':
      vb = '0 0 1000 1000';
      art = (
        <g>
          <BigHand cx={290} cy={430} fist={tens} mirror={false} jit={jit} />
          <BigHand cx={710} cy={430} fist={tens} mirror={true} jit={-jit} />
          <Glows
            g={[
              {x: 290, y: 400, rx: 170, ry: 200},
              {x: 710, y: 400, rx: 170, ry: 200},
            ]}
            red={red * 0.8}
            warm={warm}
            f={f}
            id="hands"
          />
        </g>
      );
      break;
    case 'arms':
      art = <FrontBody flex={tens} fist={tens} focus="arms" red={red} warm={warm} f={f} />;
      break;
    case 'shoulders':
      art = <FrontBody s={tens} focus="shoulders" red={red} warm={warm} f={f} />;
      break;
    case 'brow':
      vb = '270 60 460 460';
      art = <FrontBody brow={tens} closed={relaxed ? 0.9 : 0} focus="brow" red={red} warm={warm} f={f} />;
      break;
    case 'eyes':
      vb = '290 100 420 420';
      art = <FrontBody sq={tens} closed={relaxed ? 1 : 0} focus="eyes" red={red} warm={warm} f={f} />;
      break;
    case 'jaw': {
      vb = '290 150 420 420';
      const open = lastRel > 0 ? sm(t, 215.98, 216.8) * (1 - tens) : 0;
      art = <FrontBody jaw={tens} jawOpen={open} closed={0.9} focus="jaw" red={red} warm={warm} f={f} />;
      break;
    }
    case 'belly': {
      vb = '60 150 880 880';
      const breath = Math.max(sm(t, 224.62, 226.1) * (1 - sm(t, 236.93, 238.5)), 0);
      art = <FrontBody belly={tens} breath={breath} closed={0.9} focus="belly" red={red} warm={warm} f={f} />;
      break;
    }
    case 'glute':
      vb = '80 200 860 860';
      art = <LyingBody glute={tens} focus="glute" red={red} warm={warm} f={f} />;
      break;
    case 'thigh':
      vb = '60 160 900 900';
      art = <LyingBody thigh={tens} focus="thigh" red={red} warm={warm} f={f} />;
      break;
    case 'foot':
      vb = '470 230 600 600';
      art = <LyingBody foot={tens} focus="foot" red={red} warm={warm} f={f} />;
      break;
  }

  return (
    <AbsoluteFill>
      <Header pill={`NHÓM ${g.n}/10`} title={g.name} n={g.n} />
      <Stage viewBox={vb}>{art}</Stage>
      <Panel label={label} sub={sub} color={color} ring={ring} pop={pop} />
    </AbsoluteFill>
  );
};

// ---- Chuẩn bị: 48.52 -> 57.74 ----
const PrepScene: React.FC<{t: number; f: number}> = ({t, f}) => {
  const lampOff = sm(t, 52.08, 52.8);
  const breath = t > 53.88 ? 0.5 + 0.5 * Math.sin(((t - 53.88) / 4) * 2 * Math.PI - Math.PI / 2) : 0;
  let label = 'NẰM TRÊN GIƯỜNG';
  let sub = 'hoặc ngồi ghế tựa nếu thoải mái hơn';
  let ev = 48.52;
  if (t >= 53.88) {
    label = 'NHẮM MẮT · THỞ CHẬM';
    sub = 'Vài nhịp để lắng xuống';
    ev = 53.88;
  } else if (t >= 52.08) {
    label = 'TẮT BỚT ĐÈN';
    sub = 'Phòng tối dịu, yên tĩnh';
    ev = 52.08;
  }
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{background: 'black', opacity: 0.35 * lampOff}} />
      <Header pill="CHUẨN BỊ" title="TƯ THẾ THOẢI MÁI" />
      <Stage viewBox="0 160 1000 1000">
        {/* đèn */}
        <g transform="translate(830 230)">
          <circle cx={0} cy={40} r={150} fill={C.yellow} opacity={0.22 * (1 - lampOff)} />
          <path d="M -60 -40 L 60 -40 L 85 30 L -85 30 Z" fill={lampOff > 0.5 ? '#6b6b6b' : '#ffe082'} />
          {L(0, 30, 0, 160, '#9e9e9e', 10)}
          {L(-40, 160, 40, 160, '#9e9e9e', 12)}
        </g>
        <g transform="translate(20 230) scale(0.9)">
          <rect x={-10} y={-20} width={330} height={360} rx={30} fill="rgba(255,255,255,0.07)" />
          <ChairPerson />
          <text x={155} y={385} textAnchor="middle" fontFamily={FONT} fontSize={40} fill={C.yellow}>
            HOẶC
          </text>
        </g>
        <LyingBody breath={breath} focus="all" red={0} warm={t >= 53.88 ? 0.35 : 0} f={f} />
      </Stage>
      <Panel label={label} sub={sub} color={C.teal} pop={sm(t, ev, ev + 0.35)} />
    </AbsoluteFill>
  );
};

// ---- Cách làm chung: 57.74 -> 79.14 ----
const MethodScene: React.FC<{t: number; f: number}> = ({t, f}) => {
  const tens = sm(t, 63.2, 64.0) * (1 - sm(t, 69.46, 70.4)) * 0.7;
  const warm = sm(t, 71.5, 73) * (0.75 + 0.25 * Math.sin(f / 9));
  const steps = [
    {t: 63.2, text: 'HÍT VÀO\nGỒNG 5 GIÂY', c: C.red},
    {t: 69.46, text: 'THỞ RA\nBUÔNG NGAY', c: C.teal},
    {t: 71.5, text: 'NẰM YÊN\n10–20 GIÂY', c: C.warm},
  ];
  const cur = steps.reduce((a, s, i) => (t >= s.t ? i : a), -1);
  const lines: [number, string, string, string][] = [
    [57.74, 'CÁCH LÀM CHUNG', 'Áp dụng cho mỗi nhóm cơ', C.yellow],
    [63.2, 'HÍT VÀO · GỒNG 5 GIÂY', 'Gồng chặt nhóm cơ đó', C.red],
    [65.62, 'CHỈ 7/10 SỨC', 'Không cần gồng đến mức đau', '#ff8a65'],
    [69.46, 'THỞ RA · THẢ LỎNG NGAY', 'Buông ra lập tức', C.teal],
    [71.5, 'NẰM YÊN 10–20 GIÂY', 'Cảm nhận thật kỹ vùng vừa thả ra', C.warm],
    [76.28, 'NẶNG · ẤM · MỀM', 'Nặng dần, ấm dần, mềm dần', C.warm],
  ];
  const li = lines.reduce((a, l, i) => (t >= l[0] ? i : a), 0);
  const gauge = sm(t, 65.62, 66.2) * (1 - sm(t, 69.2, 69.6));
  return (
    <AbsoluteFill>
      <Header pill="CÁCH LÀM" title="MỖI NHÓM CƠ" />
      {/* 3 bước */}
      <div style={{position: 'absolute', top: 400, left: 40, right: 40, display: 'flex', gap: 18}}>
        {steps.map((s, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              borderRadius: 26,
              padding: '16px 8px',
              textAlign: 'center',
              whiteSpace: 'pre-line',
              fontFamily: FONT,
              fontSize: 38,
              lineHeight: 1.15,
              color: i === cur ? '#111' : 'rgba(255,255,255,0.75)',
              background: i === cur ? s.c : 'rgba(255,255,255,0.08)',
              border: `4px solid ${i <= cur ? s.c : 'rgba(255,255,255,0.2)'}`,
              transform: `scale(${i === cur ? 1.04 : 1})`,
            }}
          >
            {`${i + 1}. ${s.text}`}
          </div>
        ))}
      </div>
      <svg width={1000} height={900} viewBox="40 100 920 828" style={{position: 'absolute', left: 40, top: 560}}>
        <FrontBody flex={tens} fist={tens / 0.7} closed={t > 69.46 ? 0.9 : 0} focus={t < 70 ? 'arms' : 'arms'} red={tens} warm={warm} f={f} />
        {gauge > 0.01 && (
          <g opacity={gauge} transform="translate(640 150)">
            <rect x={0} y={0} width={300} height={150} rx={26} fill="rgba(10,26,43,0.9)" stroke="#ff8a65" strokeWidth={5} />
            {Array.from({length: 10}, (_, i) => (
              <rect key={i} x={22 + i * 26.5} y={26} width={20} height={60} rx={6} fill={i < 7 ? '#ff8a65' : 'rgba(255,255,255,0.2)'} />
            ))}
            <text x={150} y={130} textAnchor="middle" fontFamily={FONT} fontSize={36} fill="white">
              7/10 SỨC
            </text>
          </g>
        )}
      </svg>
      <Panel label={lines[li][1]} sub={lines[li][2]} color={lines[li][3]} pop={sm(t, lines[li][0], lines[li][0] + 0.35)} />
    </AbsoluteFill>
  );
};

// ---- Sau nhóm cuối: 301.48 -> 311.56 ----
const EndScene: React.FC<{t: number; f: number}> = ({t, f}) => {
  const breath = 0.5 + 0.5 * Math.sin(((t - 301.48) / 5) * 2 * Math.PI - Math.PI / 2);
  const wig = sm(t, 307.5, 307.9) * (1 - sm(t, 310.0, 310.3));
  const sit = sm(t, 310.2, 311.6);
  let label = 'NẰM YÊN 1–2 PHÚT';
  let sub = 'Thở ra thật chậm';
  let ev = 301.48;
  let title = 'NẰM YÊN 1–2 PHÚT';
  if (t >= 310.2) {
    label = 'NGỒI DẬY THẬT TỪ TỪ';
    sub = 'Không vội vàng';
    ev = 310.2;
    title = 'NGỒI DẬY TỪ TỪ';
  } else if (t >= 307.5) {
    label = 'CỬ ĐỘNG NHẸ TAY CHÂN';
    sub = 'Ngón tay, ngón chân';
    ev = 307.5;
    title = 'CỬ ĐỘNG NHẸ';
  } else if (t >= 304.5) {
    label = 'CẢM NHẬN CƠ THỂ';
    sub = 'Đang chùng xuống, buông lỏng';
    ev = 304.5;
  }
  return (
    <AbsoluteFill>
      <Header pill="SAU NHÓM CUỐI" title={title} />
      <Stage viewBox="0 160 1000 1000">
        <LyingBody breath={breath} wiggle={wig} sit={sit} focus="all" red={0} warm={(1 - sit) * (0.6 + 0.2 * Math.sin(f / 9))} f={f} />
      </Stage>
      <Panel label={label} sub={sub} color={C.warm} pop={sm(t, ev, ev + 0.35)} />
    </AbsoluteFill>
  );
};

// ===================== GHÉP =====================
type Seg = {a: number; b: number; render: (t: number, f: number) => React.ReactNode};
const SEGS: Seg[] = [
  {a: COVER_IN, b: 57.74, render: (t, f) => <PrepScene t={t} f={f} />},
  {a: 57.74, b: 79.14, render: (t, f) => <MethodScene t={t} f={f} />},
  ...GROUPS.map((g) => ({a: g.start, b: g.end, render: (t: number, f: number) => <GroupScene g={g} t={t} f={f} />})),
  {a: 301.48, b: COVER_OUT + 1, render: (t, f) => <EndScene t={t} f={f} />},
];

const XF = 0.35; // giây chuyển cảnh

export const ThuGian: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const cover = sm(t, COVER_IN, COVER_IN + 0.5) * (1 - sm(t, COVER_OUT, COVER_OUT + 0.5));

  return (
    <AbsoluteFill style={{background: 'black'}}>
      <OffthreadVideo src={staticFile('thugian.mp4')} />
      {cover > 0.001 && (
        <AbsoluteFill style={{opacity: cover, transform: `scale(${1.06 - 0.06 * cover})`}}>
          <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 45%, ${C.bg2} 0%, ${C.bg1} 75%)`}} />
          {SEGS.map((s, i) => {
            if (t < s.a - 0.01 || t > s.b + XF) return null;
            const op = (i === 0 ? 1 : sm(t, s.a, s.a + XF)) * (1 - sm(t, s.b, s.b + XF));
            if (op <= 0.001) return null;
            return (
              <AbsoluteFill key={i} style={{opacity: op}}>
                {s.render(t, f)}
              </AbsoluteFill>
            );
          })}
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
