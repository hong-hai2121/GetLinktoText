import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import data from './lung01.json';

// Video 01.mov "Bài tập lưng 8 động tác" (1080x1920, 30 fps, 274.83 s)
// Khung tiêu đề phía trên đầu, chữ hiệu ứng phần mở đầu, khung minh họa phía dưới
// (người tập vẽ vector, sáng vùng cơ câu nói đang nhắc), vòng đánh dấu trên người thật.
export const FPS = 30;
export const LUNG01_FRAMES = 8245;
const EX_FROM = 37.9; // cảnh tập nằm bắt đầu

type P = {x: number; y: number};
type Cue = {
  t: number;
  e: number;
  text: string;
  sub?: string;
  zone?: string;
  tag?: string;
  kind?: string;
  hold?: number;
  marks?: number[][];
};
type Ex = {n: number; name: string; start: number; end: number; info: string; pose: string; idle: string};
const CUES = data.cues as Cue[];
const EXS = data.ex as Ex[];
const INTRO = data.intro as {t: number; e: number; big: string; small: string}[];

const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ramp = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
const ease = (x: number) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const sm = (t: number, a: number, b: number) => ease(ramp(t, a, b));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const lp = (a: P, b: P, k: number): P => ({x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k)});
// bật nảy khi xuất hiện
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
  green: '#1f9d55',
  red: '#e53935',
  yellow: '#ffd54a',
  skin: '#f3c79b',
  skinD: '#d99f6f',
  hair: '#2a2018',
  coat: '#f4f7fb',
  coatD: '#c9d3df',
  pants: '#d9c8a9',
  pantsD: '#b7a27e',
};

// ===================== TƯ THẾ NGƯỜI TẬP (khung minh họa, toạ độ 1000x330) =====================
type Pose = {
  head: P;
  S: P; // vai
  Pv: P; // hông
  K: P;
  A: P;
  T: P; // mũi chân
  E: P;
  W: P;
  far?: {K: P; A: P; T: P}; // chân phía sau
  prone?: boolean;
  arch?: number; // khoảng hở lưng dưới
};

const ik = (a: P, b: P, l1: number, l2: number, up = true): P => {
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

const A0 = {x: 330, y: 292};
const footOf = (A: P): P => ({x: A.x - 52, y: A.y + 4});

// nằm ngửa, đầu bên phải (khớp với cảnh quay)
const supine = (o: {tilt?: number; hug?: number; arch?: number; lift?: number; bridge?: number}): Pose => {
  const br = o.bridge ?? 0;
  const lift = o.lift ?? 0;
  const S = {x: 720, y: 268};
  const Pv = {x: 500, y: 280 - 90 * br - 34 * lift};
  const K0 = ik(Pv, A0, 165, 160, true);
  const tl = o.tilt ?? 0;
  const drop = Math.abs(tl);
  const Kt = {x: K0.x - 16 * tl, y: K0.y + 78 * drop};
  let K = Kt;
  let A = A0;
  let T = footOf(A0);
  let E = {x: 615, y: 288};
  let W = {x: 525, y: 292};
  const hg = o.hug ?? 0;
  if (hg > 0) {
    K = lp(Kt, {x: 590, y: 128}, hg);
    A = lp(A0, {x: 440, y: 178}, hg);
    T = lp(footOf(A0), {x: 400, y: 150}, hg);
    W = lp(W, {x: K.x + 14, y: K.y + 22}, hg);
    E = lp(E, {x: 700, y: 175}, hg);
  }
  const farK = {x: Kt.x + 14, y: Kt.y - 8};
  return {
    head: {x: 806, y: 248},
    S,
    Pv,
    K,
    A,
    T,
    E,
    W,
    far: {K: farK, A: {x: A0.x + 14, y: A0.y - 6}, T: {x: A0.x - 38, y: A0.y - 2}},
    arch: o.arch ?? 0,
  };
};

// nằm sấp, đầu bên trái
const prone = (k: number): Pose => {
  const a = sm(k, 0, 0.5);
  const c = sm(k, 0.5, 1);
  const S = {x: 320, y: lerp(282, 196, c)};
  return {
    head: {x: lerp(228, 246, c), y: lerp(276, 128, c)},
    S,
    Pv: {x: 575, y: 282},
    K: {x: 735, y: 290},
    A: {x: 890, y: 294},
    T: {x: 940, y: 300},
    E: lp({x: 420, y: 294}, {x: 330, y: 296}, a),
    W: lp({x: 520, y: 296}, {x: 196, y: 298}, a),
    prone: true,
  };
};

const L = (a: P, b: P, c: string, w: number, key?: string) => (
  <line key={key} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={c} strokeWidth={w} strokeLinecap="round" />
);

const Figure: React.FC<{p: Pose}> = ({p}) => {
  const {S, Pv, K, A, T, E, W, head} = p;
  const arch = p.arch ?? 0;
  const mid = lp(S, Pv, 0.62);
  const torso = p.prone
    ? `M ${Pv.x} ${Pv.y} Q ${lerp(Pv.x, S.x, 0.5)} ${Math.max(Pv.y, S.y) + 6} ${S.x} ${S.y}`
    : `M ${Pv.x} ${Pv.y} Q ${mid.x} ${mid.y - 26 * arch} ${S.x} ${S.y}`;
  return (
    <g>
      {/* giường */}
      <rect x={20} y={300} width={960} height={32} rx={14} fill="#dfe6ee" />
      <rect x={20} y={326} width={960} height={14} rx={6} fill="#8d6e63" />
      {!p.prone && <ellipse cx={835} cy={292} rx={95} ry={20} fill="#ffffff" />}
      {/* khe hở lưng dưới */}
      {!p.prone && arch > 0.03 && (
        <path
          d={`M ${Pv.x + 10} ${Pv.y + 22} Q ${mid.x} ${mid.y + 30 - 26 * arch} ${S.x - 40} ${S.y + 30} Z`}
          fill="#0b2236"
          opacity={0.55 * arch}
        />
      )}
      {/* chân phía sau */}
      {p.far && (
        <g opacity={0.9}>
          {L(Pv, p.far.K, C.pantsD, 54)}
          {L(p.far.K, p.far.A, C.pantsD, 44)}
          {L(p.far.A, p.far.T, '#e8edf2', 24)}
        </g>
      )}
      {/* thân */}
      <path d={torso} stroke={C.coat} strokeWidth={78} fill="none" strokeLinecap="round" />
      <path d={torso} stroke={C.coatD} strokeWidth={4} fill="none" strokeDasharray="2 18" opacity={0.6} />
      {/* chân phía trước */}
      {L(Pv, K, C.pants, 58)}
      {L(K, A, C.pants, 48)}
      {L(A, T, '#ffffff', 26)}
      {/* đầu */}
      <circle cx={head.x + (p.prone ? 12 : 8)} cy={head.y + (p.prone ? -14 : 10)} r={44} fill={C.hair} />
      <circle cx={head.x} cy={head.y} r={40} fill={C.skin} />
      {p.prone ? (
        <circle cx={head.x - 24} cy={head.y - 6} r={5} fill="#3b2a1e" />
      ) : (
        <circle cx={head.x - 6} cy={head.y - 26} r={5} fill="#3b2a1e" />
      )}
      {L(lp(S, head, 0.35), lp(S, head, 0.6), C.skin, 30)}
      {/* tay */}
      {L(S, E, C.coat, 36)}
      {L(S, E, C.coatD, 2)}
      {L(E, W, C.skin, 26)}
      <circle cx={W.x} cy={W.y} r={17} fill={C.skin} />
    </g>
  );
};

const poseAt = (ex: Ex, t: number): Pose => {
  if (ex.pose === 'tilt') {
    if (t < 53.84) return supine({});
    const amp = t < 67.98 ? 0.42 : lerp(0.42, 1, sm(t, 67.98, 70));
    return supine({tilt: amp * Math.sin(((t - 53.84) / 5) * 2 * Math.PI)});
  }
  if (ex.pose === 'hug') {
    let h = 0;
    if (t >= 97.04 && t < 112.24) {
      h = 0.55 * sm(t, 97.04, 100) + 0.45 * sm(t, 100.92, 102.4) - 0.14 * sm(t, 105.12, 106) + 0.14 * sm(t, 107.1, 108);
    } else if (t >= 112.24) {
      const c = ((t - 112.24) % 9) / 9;
      h = sm(c, 0.05, 0.25) * (1 - sm(c, 0.78, 0.95));
    }
    return supine({hug: h});
  }
  if (ex.pose === 'pelvic') {
    let arch = 1;
    let lift = 0;
    if (t >= 145.75 && t < 149.33) arch = 1 - sm(t, 145.75, 147);
    else if (t >= 149.33 && t < 152.95) arch = sm(t, 149.33, 150.5);
    else if (t >= 152.95 && t < 158.59) {
      const c = ((t - 152.95) % 2.8) / 2.8;
      lift = Math.sin(c * Math.PI);
      arch = 0.4;
    } else if (t >= 158.59 && t < 166.31) arch = 1 - sm(t, 158.59, 159.6);
    else if (t >= 166.31) {
      const c = ((t - 166.31) % 6) / 6;
      arch = 1 - sm(c, 0.1, 0.3) * (1 - sm(c, 0.8, 0.95));
    }
    return supine({arch, lift});
  }
  if (ex.pose === 'bridge') {
    let b = 0;
    if (t >= 191.06 && t < 205) b = sm(t, 191.06, 193) * (1 - sm(t, 202.39, 205));
    else if (t >= 205) {
      const c = ((t - 205) % 10) / 10;
      b = sm(c, 0.05, 0.25) * (1 - sm(c, 0.72, 0.98));
    }
    return supine({bridge: b});
  }
  // nhân sư
  let k = 0;
  if (t >= 255.98) k = 0.5 * sm(t, 255.98, 257.6) + 0.5 * sm(t, 259.38, 261);
  return prone(k);
};

const zonePts = (p: Pose, z: string): P[] => {
  switch (z) {
    case 'knee':
      return [p.K];
    case 'arm':
      return [lp(p.E, p.W, 0.4)];
    case 'belly':
      return [{...lp(p.Pv, p.S, 0.38), y: lp(p.Pv, p.S, 0.38).y - 30}];
    case 'lowback':
      return [{...lp(p.Pv, p.S, 0.22), y: lp(p.Pv, p.S, 0.22).y + 26}];
    case 'pelvis':
    case 'hip':
      return [p.Pv];
    case 'glute':
      return [{x: p.Pv.x - 12, y: p.Pv.y + 22}];
    case 'feet':
      return [lp(p.A, p.T, 0.4)];
    case 'line':
      return [p.S, p.Pv, p.K];
    case 'forearm':
      return [lp(p.E, p.W, 0.5)];
    case 'chest':
      return [lp(p.S, p.Pv, 0.18)];
    case 'eyes':
      return [{x: p.head.x - 22, y: p.head.y - 6}];
    default:
      return [];
  }
};

export const Check: React.FC<{x: number; y: number; ok: boolean; s: number}> = ({x, y, ok, s}) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <circle r={34} fill={ok ? C.green : C.red} stroke="#fff" strokeWidth={5} />
    {ok ? (
      <path d="M -15 1 L -4 13 L 17 -12" stroke="#fff" strokeWidth={9} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    ) : (
      <path d="M -13 -13 L 13 13 M 13 -13 L -13 13" stroke="#fff" strokeWidth={9} strokeLinecap="round" />
    )}
  </g>
);

export const HoldClock: React.FC<{t: number; t0: number; n?: number}> = ({t, t0, n = 5}) => {
  const x = clamp((t - t0) / n);
  const left = Math.max(1, Math.ceil(n - (t - t0)));
  const r = 44;
  const cir = 2 * Math.PI * r;
  return (
    <g transform={`translate(872 100) scale(${pop(t, t0)})`}>
      <circle r={r + 10} fill={C.navy} />
      <circle r={r} fill="none" stroke="#ffffff33" strokeWidth={10} />
      <circle r={r} fill="none" stroke={C.yellow} strokeWidth={10} strokeDasharray={`${cir * (1 - x)} ${cir}`} transform="rotate(-90)" strokeLinecap="round" />
      <text y={16} textAnchor="middle" fontFamily={FONT} fontSize={46} fill="#fff">
        {x >= 1 ? '✓' : left}
      </text>
    </g>
  );
};

// ===================== KHUNG TIÊU ĐỀ (xanh viền, chữ đen, từ khoá đỏ) =====================
const Title: React.FC<{t: number}> = ({t}) => {
  const k = sm(t, EX_FROM - 0.35, EX_FROM + 0.35); // 0 = lớn (mở đầu), 1 = gọn (cảnh tập)
  const s = pop(t, 0.2);
  const big = 1 - k;
  const shine = ((t * 0.35) % 1.6) - 0.3;
  return (
    <>
      {big > 0.01 && (
        <div
          style={{
            position: 'absolute',
            left: 70,
            top: 60,
            width: 940,
            height: 300,
            borderRadius: 40,
            background: '#ffffff',
            border: '10px solid #1e88e5',
            boxShadow: '0 14px 40px rgba(0,0,0,0.35)',
            transform: `translateY(${-60 * k}px) scale(${s * (1 - 0.3 * k)})`,
            opacity: big,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
          }}
        >
          <div style={{fontFamily: SERIF, fontWeight: 700, fontSize: 112, lineHeight: 1.05, color: '#111'}}>BÀI TẬP LƯNG</div>
          <div style={{fontFamily: SERIF, fontWeight: 700, fontSize: 124, lineHeight: 1.05, color: C.red}}>
            {'8 ĐỘNG TÁC'.split('').map((ch, i) => (
              <span key={i} style={{display: 'inline-block', transform: `translateY(${-26 * Math.max(0, Math.sin((t - 0.6 - i * 0.06) * 6)) * (t < 2.2 ? 1 : 0)}px)`}}>
                {ch === ' ' ? ' ' : ch}
              </span>
            ))}
          </div>
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: `${shine * 100}%`,
              width: 120,
              background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.75), transparent)',
              transform: 'skewX(-20deg)',
            }}
          />
        </div>
      )}
      {k > 0.01 && (
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
            opacity: k,
            transform: `scale(${lerp(1.25, 1, k)})`,
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
      )}
    </>
  );
};

// ===================== THẺ ĐỘNG TÁC (dưới tiêu đề) =====================
const ExChip: React.FC<{ex: Ex; t: number}> = ({ex, t}) => {
  const s = pop(t, ex.start);
  const o = fadeIO(t, ex.start, ex.end + 0.1, 0.2);
  const flash = Math.exp(-(t - ex.start) * 3);
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
      <div
        style={{
          fontFamily: FONT,
          fontSize: 40,
          background: C.yellow,
          color: C.navy,
          padding: '2px 26px',
          borderRadius: 40,
          letterSpacing: 2,
        }}
      >
        ĐỘNG TÁC {ex.n}
      </div>
      <div style={{fontFamily: FONT, fontSize: ex.name.length > 14 ? 74 : 86, lineHeight: 1.1, marginTop: 6, textShadow: '0 4px 12px rgba(0,0,0,0.3)'}}>
        {ex.name}
      </div>
      <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 40, color: '#e9fffb', opacity: ramp(t, ex.start + 0.4, ex.start + 0.9)}}>{ex.info}</div>
    </div>
  );
};

// ===================== KHUNG MINH HOẠ (phía dưới) =====================
// Khung chữ hướng dẫn phía dưới (đã có người thật minh họa nên không vẽ người giả)
const Panel: React.FC<{ex: Ex; t: number}> = ({ex, t}) => {
  const cue = CUES.find((c) => c.t >= ex.start - 0.01 && t >= c.t && t < c.e);
  const o = fadeIO(t, Math.max(ex.start, EX_FROM), ex.end + 0.1, 0.3);
  const text = cue ? cue.text : ex.idle;
  const key = cue ? cue.t : ex.start;
  const s = pop(t, key);
  const icon = cue && (cue.kind === 'ok' || cue.kind === 'no');
  const side = icon || cue?.hold ? 120 : 0;
  return (
    <div
      style={{
        position: 'absolute',
        left: 40,
        top: 1530,
        width: 1000,
        height: 220,
        borderRadius: 36,
        background: 'rgba(11,34,54,0.88)',
        border: '4px solid rgba(255,255,255,0.25)',
        boxShadow: '0 10px 30px rgba(0,0,0,0.3)',
        opacity: o,
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
        <div style={{fontFamily: FONT, fontSize: text.length > 16 ? 56 : 66, color: cue?.kind === 'no' ? '#ff8a80' : '#ffffff', lineHeight: 1.1}}>{text}</div>
        {cue?.sub ? <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 42, color: C.yellow, marginTop: 6}}>{cue.sub}</div> : null}
      </div>
      {cue?.hold ? (
        <svg viewBox="812 40 120 120" style={{position: 'absolute', right: 10, top: 50, width: 120, height: 120}}>
          <HoldClock t={t} t0={cue.t} />
        </svg>
      ) : null}
    </div>
  );
};


// ===================== HIỆU ỨNG HƯỚNG DẪN TRÊN NGƯỜI THẬT =====================
export type Fx = {
  type: string;
  p?: number[];
  a?: number[];
  b?: number[];
  c?: number[];
  at?: number[];
  from?: number[];
  to?: number[];
  label?: string;
  curve?: number;
  slow?: number;
  w?: number;
  h?: number;
  amp?: number;
  grow?: number;
  kind?: string;
  x1?: number;
  x2?: number;
  y?: number;
  r?: number;
};
const DEMO = ((data as {demo?: {t: number; e: number; fx: Fx[]}[]}).demo ?? []) as {t: number; e: number; fx: Fx[]}[];
const YEL = '#ffe14d';

const Head: React.FC<{x: number; y: number; ang: number; col?: string; s?: number}> = ({x, y, ang, col = YEL, s = 1}) => (
  <g transform={`translate(${x} ${y}) rotate(${(ang * 180) / Math.PI}) scale(${s})`}>
    <path d="M 8 0 L -34 -24 L -24 0 L -34 24 Z" fill={col} stroke="#000" strokeOpacity={0.4} strokeWidth={3} strokeLinejoin="round" />
  </g>
);

export const Label: React.FC<{x: number; y: number; text: string; o: number}> = ({x, y, text, o}) => (
  <g transform={`translate(${x} ${y})`} opacity={o}>
    <rect x={-(text.length * 15 + 26)} y={-30} width={text.length * 30 + 52} height={58} rx={29} fill="#0b2236" fillOpacity={0.85} stroke={YEL} strokeWidth={3} />
    <text y={12} textAnchor="middle" fontFamily={FONT} fontSize={34} fill={YEL}>
      {text}
    </text>
  </g>
);

const Arrow: React.FC<{fx: Fx; t: number; t0: number}> = ({fx, t, t0}) => {
  const A = {x: fx.from![0], y: fx.from![1]};
  const B = {x: fx.to![0], y: fx.to![1]};
  const dx = B.x - A.x;
  const dy = B.y - A.y;
  const len = Math.hypot(dx, dy);
  const cv = fx.curve ?? 0;
  const Q = {x: (A.x + B.x) / 2 - (dy / len) * cv, y: (A.y + B.y) / 2 + (dx / len) * cv};
  const per = fx.slow ? 3 : 1.5;
  const k = ease(clamp(((t - t0) % per) / (per * 0.6)));
  const tip = {x: lerp(lerp(A.x, Q.x, k), lerp(Q.x, B.x, k), k), y: lerp(lerp(A.y, Q.y, k), lerp(Q.y, B.y, k), k)};
  const tan = {x: lerp(Q.x, B.x, k) - lerp(A.x, Q.x, k), y: lerp(Q.y, B.y, k) - lerp(A.y, Q.y, k)};
  const ang = Math.atan2(tan.y, tan.x);
  const L2 = len * 1.15;
  const d = `M ${A.x} ${A.y} Q ${Q.x} ${Q.y} ${B.x} ${B.y}`;
  return (
    <g>
      <path d={d} stroke="#000" strokeOpacity={0.35} strokeWidth={22} fill="none" strokeLinecap="round" strokeDasharray={`${L2 * k} ${L2}`} />
      <path d={d} stroke={YEL} strokeWidth={13} fill="none" strokeLinecap="round" strokeDasharray={`${L2 * k} ${L2}`} />
      <path d={d} stroke={YEL} strokeOpacity={0.25} strokeWidth={13} fill="none" strokeLinecap="round" />
      <Head x={tip.x} y={tip.y} ang={ang} s={1.15} />
      {fx.label ? <Label x={Q.x + (Q.x > 700 ? -190 : 190)} y={(A.y + B.y) / 2} text={fx.label} o={ramp(t, t0 + 0.2, t0 + 0.5)} /> : null}
    </g>
  );
};

export const FxOne: React.FC<{fx: Fx; t: number; t0: number; t1: number; f: number}> = ({fx, t, t0, t1, f}) => {
  const pulse = 0.5 + 0.5 * Math.sin(f / 3.2);
  switch (fx.type) {
    case 'arrow':
      return <Arrow fx={fx} t={t} t0={t0} />;
    case 'angle': {
      const P0 = {x: fx.p![0], y: fx.p![1]};
      const ua = Math.atan2(fx.a![1] - P0.y, fx.a![0] - P0.x);
      const ub = Math.atan2(fx.b![1] - P0.y, fx.b![0] - P0.x);
      const k = sm(t, t0, t0 + 0.6);
      const r = 70;
      const pt = (an: number, rr: number) => `${P0.x + Math.cos(an) * rr} ${P0.y + Math.sin(an) * rr}`;
      const sq = 38;
      return (
        <g>
          {[ua, ub].map((an, i) => (
            <line key={i} x1={P0.x} y1={P0.y} x2={P0.x + Math.cos(an) * 220 * k} y2={P0.y + Math.sin(an) * 220 * k} stroke="#fff" strokeWidth={8} strokeDasharray="18 10" strokeLinecap="round" />
          ))}
          <path d={`M ${pt(ua, sq)} L ${P0.x + Math.cos(ua) * sq + Math.cos(ub) * sq} ${P0.y + Math.sin(ua) * sq + Math.sin(ub) * sq} L ${pt(ub, sq)}`} stroke={YEL} strokeWidth={7} fill="none" opacity={k} />
          <path d={`M ${pt(ua, r)} A ${r} ${r} 0 0 0 ${pt(ub, r)}`} stroke={YEL} strokeWidth={6} fill="none" opacity={k} />
          <Label x={P0.x + Math.cos((ua + ub) / 2) * 135} y={P0.y + Math.sin((ua + ub) / 2) * 135 + 10} text={fx.label ?? '90°'} o={k} />
        </g>
      );
    }
    case 'swing': {
      const c = {x: fx.c![0], y: fx.c![1]};
      const grow = fx.grow ? lerp(fx.amp ?? 1, 1, sm(t, t0 + 3, t1 - 1)) : fx.amp ?? 1;
      const w = (fx.w ?? 300) * grow;
      const h = (fx.h ?? 120) * grow;
      const L1 = {x: c.x - w / 2, y: c.y};
      const R1 = {x: c.x + w / 2, y: c.y};
      const Q = {x: c.x, y: c.y - 2 * h};
      const u = 0.5 + 0.5 * Math.sin((t - t0) * 1.3);
      const ball = {x: lerp(lerp(L1.x, Q.x, u), lerp(Q.x, R1.x, u), u), y: lerp(lerp(L1.y, Q.y, u), lerp(Q.y, R1.y, u), u)};
      const d = `M ${L1.x} ${L1.y} Q ${Q.x} ${Q.y} ${R1.x} ${R1.y}`;
      const o = sm(t, t0, t0 + 0.4);
      return (
        <g opacity={o}>
          <path d={d} stroke="#000" strokeOpacity={0.35} strokeWidth={20} fill="none" />
          <path d={d} stroke={YEL} strokeWidth={11} fill="none" strokeDasharray="22 12" strokeDashoffset={-f * 2} />
          <Head x={L1.x} y={L1.y} ang={Math.atan2(L1.y - Q.y, L1.x - Q.x)} />
          <Head x={R1.x} y={R1.y} ang={Math.atan2(R1.y - Q.y, R1.x - Q.x)} />
          <circle cx={ball.x} cy={ball.y} r={20} fill="#fff" stroke={YEL} strokeWidth={6} />
          <Label x={c.x} y={c.y - h - 70} text="TRÁI ↔ PHẢI" o={o} />
        </g>
      );
    }
    case 'squeeze': {
      const c = {x: fx.c![0], y: fx.c![1]};
      return (
        <g>
          {[0, 1, 2].map((i) => {
            const ph = (((t - t0) * 0.9 + i / 3) % 1 + 1) % 1;
            return <circle key={i} cx={c.x} cy={c.y} r={lerp(150, 30, ph)} fill="none" stroke={YEL} strokeWidth={7} opacity={Math.sin(ph * Math.PI)} />;
          })}
          {[-1, 1].map((sd) => (
            <Head key={sd} x={c.x + sd * (95 - 20 * pulse)} y={c.y} ang={sd > 0 ? Math.PI : 0} />
          ))}
          <Label x={c.x} y={c.y - 170} text="SIẾT NHẸ" o={ramp(t, t0 + 0.2, t0 + 0.5)} />
        </g>
      );
    }
    case 'floor': {
      const k = sm(t, t0, t0 + 0.5);
      const x2 = lerp(fx.x1!, fx.x2!, k);
      return (
        <g>
          <line x1={fx.x1} y1={fx.y} x2={x2} y2={fx.y} stroke="#00e676" strokeOpacity={0.35 + 0.3 * pulse} strokeWidth={30} strokeLinecap="round" />
          <line x1={fx.x1} y1={fx.y} x2={x2} y2={fx.y} stroke="#b9f6ca" strokeWidth={8} strokeLinecap="round" />
        </g>
      );
    }
    case 'rotate': {
      const c = {x: fx.c![0], y: fx.c![1]};
      const r = fx.r ?? 105;
      const rot = 25 * Math.sin((t - t0) * 2.2);
      const a0 = (-150 * Math.PI) / 180;
      const a1 = (120 * Math.PI) / 180;
      const P1 = {x: c.x + Math.cos(a0) * r, y: c.y + Math.sin(a0) * r};
      const P2 = {x: c.x + Math.cos(a1) * r, y: c.y + Math.sin(a1) * r};
      return (
        <g transform={`rotate(${rot} ${c.x} ${c.y})`} opacity={sm(t, t0, t0 + 0.4)}>
          <path d={`M ${P1.x} ${P1.y} A ${r} ${r} 0 1 1 ${P2.x} ${P2.y}`} stroke="#000" strokeOpacity={0.35} strokeWidth={20} fill="none" />
          <path d={`M ${P1.x} ${P1.y} A ${r} ${r} 0 1 1 ${P2.x} ${P2.y}`} stroke={YEL} strokeWidth={11} fill="none" />
          <Head x={P2.x} y={P2.y} ang={a1 + Math.PI / 2} />
        </g>
      );
    }
    case 'beam': {
      const k = sm(t, t0, t0 + 0.5);
      const x2 = lerp(fx.from![0], fx.to![0], k);
      const y2 = lerp(fx.from![1], fx.to![1], k);
      return (
        <g>
          <line x1={fx.from![0]} y1={fx.from![1]} x2={x2} y2={y2} stroke={YEL} strokeOpacity={0.3 + 0.3 * pulse} strokeWidth={46} strokeLinecap="round" />
          <line x1={fx.from![0]} y1={fx.from![1]} x2={x2} y2={y2} stroke="#fff" strokeWidth={8} strokeLinecap="round" />
        </g>
      );
    }
    case 'sight': {
      const A = {x: fx.from![0], y: fx.from![1]};
      const B = {x: fx.to![0], y: fx.to![1]};
      const k = sm(t, t0, t0 + 0.5);
      const E2 = lp(A, B, k);
      return (
        <g>
          <line x1={A.x} y1={A.y} x2={E2.x} y2={E2.y} stroke={YEL} strokeWidth={9} strokeDasharray="20 14" strokeDashoffset={f * 3} />
          <Head x={E2.x} y={E2.y} ang={Math.atan2(B.y - A.y, B.x - A.x)} />
        </g>
      );
    }
    case 'updown': {
      const c = {x: fx.c![0], y: fx.c![1]};
      const bob = 18 * Math.sin((t - t0) * 2);
      return (
        <g opacity={sm(t, t0, t0 + 0.4)}>
          <line x1={c.x} y1={c.y - 90 + bob} x2={c.x} y2={c.y + 90 + bob} stroke="#000" strokeOpacity={0.35} strokeWidth={20} strokeLinecap="round" />
          <line x1={c.x} y1={c.y - 90 + bob} x2={c.x} y2={c.y + 90 + bob} stroke={YEL} strokeWidth={11} strokeLinecap="round" />
          <Head x={c.x} y={c.y - 110 + bob} ang={-Math.PI / 2} />
          <Head x={c.x} y={c.y + 110 + bob} ang={Math.PI / 2} />
          {fx.label === '' ? null : <Label x={c.x + 190} y={c.y + bob} text={fx.label ?? 'NÂNG · HẠ'} o={1} />}
        </g>
      );
    }
    case 'mark':
      return <Check x={fx.at![0]} y={fx.at![1]} ok={fx.kind === 'ok'} s={1.5 * pop(t, t0 + 0.2)} />;
    default:
      return null;
  }
};

const BodyFx: React.FC<{t: number; f: number}> = ({t, f}) => {
  const cue = CUES.find((c) => t >= c.t && t < c.e && (c as {fx?: Fx[]}).fx);
  const dm = DEMO.find((d) => t >= d.t && t < d.e);
  const src = cue ? {t: cue.t, e: cue.e, fx: (cue as {fx?: Fx[]}).fx!} : dm;
  if (!src) return null;
  const o = fadeIO(t, src.t, src.e, 0.25);
  return (
    <svg viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, width: 1080, height: 1920, opacity: o}}>
      {src.fx.map((fx, i) => (
        <FxOne key={i} fx={fx} t={t} t0={src.t} t1={src.e} f={f} />
      ))}
    </svg>
  );
};

// ===================== ĐÁNH DẤU TRÊN NGƯỜI THẬT =====================
const Marks: React.FC<{t: number; f: number}> = ({t, f}) => {
  const cue = CUES.find((c) => t >= c.t && t < c.e && c.marks && c.marks.length);
  if (!cue || !cue.marks) return null;
  const o = fadeIO(t, cue.t, cue.e, 0.2);
  const s = pop(t, cue.t);
  const pulse = 0.5 + 0.5 * Math.sin(f / 3.2);
  const ms = cue.marks.map((m) => ({x: m[0], y: m[1]}));
  const col = cue.kind === 'no' ? '#ff5252' : C.yellow;
  const top = ms.reduce((a, b) => (b.y < a.y ? b : a), ms[0]);
  const tagX = clamp(top.x, 170, 910);
  const tagY = Math.max(top.y - 150, 480);
  return (
    <svg viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, width: 1080, height: 1920, opacity: o}}>
      <defs>
        <radialGradient id="mglow">
          <stop offset="0%" stopColor={col} stopOpacity={0.55} />
          <stop offset="60%" stopColor={col} stopOpacity={0.25} />
          <stop offset="100%" stopColor={col} stopOpacity={0} />
        </radialGradient>
      </defs>
      {cue.kind === 'line' ? (
        <>
          <polyline points={ms.map((q) => `${q.x},${q.y}`).join(' ')} stroke="#000" strokeOpacity={0.35} strokeWidth={16} fill="none" />
          <polyline points={ms.map((q) => `${q.x},${q.y}`).join(' ')} stroke={col} strokeWidth={9} fill="none" strokeDasharray="26 16" strokeDashoffset={-f * 3} />
          {ms.map((q, i) => (
            <circle key={i} cx={q.x} cy={q.y} r={22 * s} fill={col} stroke="#fff" strokeWidth={5} />
          ))}
        </>
      ) : (
        ms.map((q, i) => (
          <g key={i} transform={`translate(${q.x} ${q.y}) scale(${s})`}>
            <circle r={78 + 26 * pulse} fill="none" stroke={col} strokeOpacity={1 - pulse} strokeWidth={6} />
            <circle r={110} fill="url(#mglow)" />
            <circle r={74} fill={col} fillOpacity={0} stroke={col} strokeWidth={9} />
            <circle r={74} fill="none" stroke="#000" strokeOpacity={0.25} strokeWidth={2} />
          </g>
        ))
      )}
      {/* nhãn + đường chỉ */}
      <g opacity={ramp(t, cue.t + 0.15, cue.t + 0.4)}>
        <line x1={top.x} y1={top.y - (cue.kind === 'line' ? 24 : 80)} x2={tagX} y2={tagY + 30} stroke="#fff" strokeWidth={5} />
        <g transform={`translate(${tagX} ${tagY})`}>
          <rect x={-(cue.tag!.length * 17 + 34)} y={-36} width={cue.tag!.length * 34 + 68} height={70} rx={35} fill={col} stroke="#fff" strokeWidth={4} />
          <text y={14} textAnchor="middle" fontFamily={FONT} fontSize={40} fill={C.navy}>
            {cue.tag}
          </text>
        </g>
      </g>
    </svg>
  );
};

// ===================== CHỮ HIỆU ỨNG PHẦN MỞ ĐẦU =====================
const IntroText: React.FC<{t: number}> = ({t}) => {
  const it = INTRO.find((c) => t >= c.t && t < c.e);
  // tên người hướng dẫn
  const nameO = fadeIO(t, 0.4, 5.3, 0.3);
  return (
    <>
      {nameO > 0 && (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: 1560,
            display: 'flex',
            justifyContent: 'center',
            opacity: nameO,
            transform: `translateX(${(1 - ease(ramp(t, 0.4, 1.0))) * -600}px)`,
          }}
        >
          <div style={{fontFamily: FONT, fontSize: 56, color: '#fff', background: C.teal, padding: '12px 40px', borderRadius: 50, boxShadow: '0 8px 24px rgba(0,0,0,0.35)'}}>
            Thạc sĩ Đức hướng dẫn
          </div>
        </div>
      )}
      {it && (
        <div
          style={{
            position: 'absolute',
            left: 50,
            width: 980,
            top: 1440,
            opacity: fadeIO(t, it.t, it.e, 0.2),
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}
        >
          <div
            style={{
              background: '#ffffff',
              borderRadius: 30,
              borderLeft: `18px solid ${C.teal}`,
              padding: '14px 40px 18px',
              boxShadow: '0 12px 34px rgba(0,0,0,0.35)',
              transform: `scale(${pop(t, it.t)}) rotate(${(1 - ramp(t, it.t, it.t + 0.4)) * -4}deg)`,
              textAlign: 'center',
            }}
          >
            <div style={{fontFamily: FONT, fontSize: Math.min(92, 1350 / it.big.length), color: C.navy, whiteSpace: 'nowrap'}}>
              {it.big.split(' ').map((w, i) => (
                <span key={i} style={{display: 'inline-block', marginRight: 22, opacity: ramp(t, it.t + i * 0.12, it.t + i * 0.12 + 0.15), transform: `translateY(${(1 - pop(t, it.t + i * 0.12)) * 40}px)`}}>
                  {w}
                </span>
              ))}
            </div>
            <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 48, color: C.red, opacity: ramp(t, it.t + 0.45, it.t + 0.75)}}>{it.small}</div>
          </div>
        </div>
      )}
    </>
  );
};

export const Lung01: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const ex = [...EXS].reverse().find((e) => t >= e.start);
  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      <OffthreadVideo src={staticFile('lung01.mp4')} muted />
      {t < EX_FROM + 0.3 && <IntroText t={t} />}
      {ex && t >= EX_FROM - 0.2 && <ExChip ex={ex} t={t} />}
      {ex && t >= EX_FROM && <BodyFx t={t} f={f} />}
      {ex && t >= EX_FROM && <Marks t={t} f={f} />}
      {ex && t >= EX_FROM && <Panel ex={ex} t={t} />}
      <Title t={t} />
    </AbsoluteFill>
  );
};
