import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import {Check, Fx, FxOne, HoldClock} from './Lung01';
import DATA from './d78.json';

// "Tập cổ gáy.mov" (1080x1920, 30 fps, 586 s)
// - đoạn ngồi nói (đầu + cuối): phụ đề lời nói; tiêu đề trên đỉnh đầu chỉ 10 giây đầu
// - đoạn tập có lời: chữ mô tả động tác + hiệu ứng trên người thật
// - đoạn tập không lời: vẫn có hiệu ứng (mũi tên chuyển động, vầng sáng, đồng hồ giữ 30 giây)
export const D78_FRAMES = 3432;
const FPS = 30;

type P = number[];
type Cue = {t: number; e: number; text: string; sub?: string; kind?: string; hold?: number; marks?: P[]; tag?: string; fx?: Fx[]};
type Ex = {n: number; name: string; start: number; end: number; info: string};
const D = DATA as unknown as {cover: number[]; ex: Ex[]; cues: Cue[]; demo: Cue[]; diagram: (Cue & {phase: string})[]};

const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ramp = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
const ease = (x: number) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
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
const NAVY = '#0b2236';
const TEAL = '#12a89c';
const RED = '#e53935';
const YEL = '#ffd54a';

// ---------- thẻ động tác (gọn, sát mép trên) ----------
const Chip: React.FC<{ex: Ex; t: number}> = ({ex, t}) => {
  const s = pop(t, ex.start);
  const o = fadeIO(t, ex.start, ex.end + 0.1, 0.2);
  const flash = Math.exp(-(t - ex.start) * 3);
  return (
    <div
      style={{
        position: 'absolute',
        left: 70,
        top: 34,
        width: 940,
        height: 196,
        borderRadius: 32,
        background: `linear-gradient(135deg, ${TEAL}, #0d6e8c)`,
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
      <div style={{fontFamily: FONT, fontSize: 36, background: YEL, color: NAVY, padding: '0 24px', borderRadius: 40, letterSpacing: 2}}>ĐỘNG TÁC {ex.n} / 8</div>
      <div style={{fontFamily: FONT, fontSize: ex.name.length > 15 ? 70 : 80, lineHeight: 1.1, marginTop: 4, textShadow: '0 4px 12px rgba(0,0,0,0.3)', whiteSpace: 'nowrap'}}>{ex.name}</div>
      <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 36, color: '#e9fffb', opacity: ramp(t, ex.start + 0.4, ex.start + 0.9)}}>{ex.info}</div>
    </div>
  );
};

// ---------- khung chữ mô tả động tác ----------
const Panel: React.FC<{t: number; c: Cue}> = ({t, c}) => {
  const s = pop(t, c.t);
  const o = fadeIO(t, c.t, c.e, 0.2);
  const icon = c.kind === 'ok' || c.kind === 'no';
  const side = icon || c.hold ? 120 : 0;
  return (
    <div
      style={{
        position: 'absolute',
        left: 40,
        top: 1570,
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
          <Check x={0} y={0} ok={c.kind === 'ok'} s={1.4 * pop(t, c.t + 0.15)} />
        </svg>
      ) : null}
      <div style={{position: 'absolute', left: side, right: side, textAlign: 'center'}}>
        <div style={{fontFamily: FONT, fontSize: side ? (c.text.length > 28 ? 34 : c.text.length > 22 ? 40 : c.text.length > 16 ? 48 : 58) : c.text.length > 26 ? 44 : c.text.length > 20 ? 52 : 64, color: c.kind === 'no' ? '#ff8a80' : '#ffffff', lineHeight: 1.1, whiteSpace: 'nowrap'}}>{c.text}</div>
        {c.sub ? <div style={{fontFamily: FONT_B, fontWeight: 700, fontSize: 40, color: YEL, marginTop: 6}}>{c.sub}</div> : null}
      </div>
      {c.hold ? (
        <svg viewBox="812 40 120 120" style={{position: 'absolute', right: 10, top: 50, width: 120, height: 120}}>
          <HoldClock t={t} t0={c.t} n={c.hold} />
        </svg>
      ) : null}
    </div>
  );
};

// ---------- vầng sáng + nhãn + hiệu ứng trên người thật ----------
const BodyFx: React.FC<{t: number; f: number; c: Cue}> = ({t, f, c}) => {
  const o = fadeIO(t, c.t, c.e, 0.25);
  const s = pop(t, c.t);
  const pulse = 0.5 + 0.5 * Math.sin(f / 3.2);
  const col = c.kind === 'no' ? '#ff5252' : '#ffe14d';
  const ms = c.marks ?? [];
  const top = ms.length ? ms.reduce((a, b) => (b[1] < a[1] ? b : a), ms[0]) : null;
  const tagX = top ? clamp(top[0] < 540 ? top[0] - 60 : top[0] + 60, 200, 880) : 0;
  const tagY = top ? top[1] - 170 : 0;
  return (
    <svg viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, width: 1080, height: 1920, opacity: o}}>
      <defs>
        <radialGradient id="cgglow">
          <stop offset="0%" stopColor={col} stopOpacity={0.55} />
          <stop offset="60%" stopColor={col} stopOpacity={0.22} />
          <stop offset="100%" stopColor={col} stopOpacity={0} />
        </radialGradient>
      </defs>
      {ms.map((m, i) => (
        <g key={i} transform={`translate(${m[0]} ${m[1]}) scale(${s})`}>
          <circle r={115} fill="url(#cgglow)" />
          <circle r={78 + 26 * pulse} fill="none" stroke={col} strokeOpacity={1 - pulse} strokeWidth={6} />
          <circle r={74} fill="none" stroke={col} strokeWidth={9} />
        </g>
      ))}
      {(c.fx ?? []).map((fx, i) => (
        <FxOne key={i} fx={fx} t={t} t0={c.t} t1={c.e} f={f} />
      ))}
      {top && c.tag && (
        <g opacity={ramp(t, c.t + 0.15, c.t + 0.4)}>
          {ms.map((m, i) => (
            <line key={i} x1={m[0]} y1={m[1] - 78} x2={tagX} y2={tagY + 30} stroke="#fff" strokeWidth={5} />
          ))}
          <g transform={`translate(${tagX} ${tagY})`}>
            <rect x={-(c.tag.length * 16 + 34)} y={-36} width={c.tag.length * 32 + 68} height={70} rx={35} fill={col} stroke="#fff" strokeWidth={4} />
            <text y={14} textAnchor="middle" fontFamily={FONT} fontSize={38} fill={NAVY}>
              {c.tag}
            </text>
          </g>
        </g>
      )}
    </svg>
  );
};

// ---------- minh hoạ cơ chế (thay đoạn màn hình đen đầu động tác 8) ----------
const TRAP = 'M 492 770 Q 470 850 360 885 Q 260 910 205 960 Q 330 975 430 935 Q 495 905 512 850 Z M 588 770 Q 610 850 720 885 Q 820 910 875 960 Q 750 975 650 935 Q 585 905 568 850 Z';
const Diagram: React.FC<{t: number; f: number}> = ({t, f}) => {
  const [a, b] = D.cover;
  if (t < a - 0.1 || t > b + 0.1) return null;
  const o = Math.min(ramp(t, a, a + 0.5), 1 - ramp(t, b - 0.4, b));
  const cur = [...D.diagram].reverse().find((x) => t >= x.t) ?? D.diagram[0];
  const ph = t < D.diagram[0].t ? 'intro' : cur.phase;
  const pulse = 0.5 + 0.5 * Math.sin(f / 3);
  const red = ph === 'tense' ? 0.55 + 0.3 * pulse : ph === 'pump' || ph === 'brain' ? 0.45 : ph === 'calm' ? 0.25 : 0.3;
  const trapCol = ph === 'tense' ? '#e53935' : ph === 'calm' ? '#4fc3f7' : '#ff7043';
  const shake = ph === 'tense' ? Math.sin(f * 1.7) * 3 : 0;
  // hạt máu chạy dọc cơ thang (vai → cổ) rồi lên não
  const dots: React.ReactNode[] = [];
  if (ph === 'pump' || ph === 'brain') {
    for (let i = 0; i < 14; i++) {
      const u = (((t * 0.55 + i / 14) % 1) + 1) % 1;
      const side = i % 2 ? 1 : -1;
      const x = ph === 'pump' ? 540 + side * (330 - 280 * u) : 540 + side * (40 - 30 * u);
      const y = ph === 'pump' ? 950 - 120 * u + 30 * Math.sin(u * Math.PI) : 900 - 360 * u;
      dots.push(<circle key={i} cx={x} cy={y} r={11} fill="#ff1744" stroke="#fff" strokeWidth={3} opacity={Math.sin(u * Math.PI)} />);
    }
  }
  return (
    <svg viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, width: 1080, height: 1920, opacity: o}}>
      <defs>
        <radialGradient id="dgSkin" cx="0.6" cy="0.35" r="0.8">
          <stop offset="0%" stopColor="#f8d6b6" />
          <stop offset="100%" stopColor="#efc097" />
        </radialGradient>
        <linearGradient id="dgCoat" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#dfe6ee" />
        </linearGradient>
        <radialGradient id="dgBrain">
          <stop offset="0%" stopColor="#ff80ab" stopOpacity={0.9} />
          <stop offset="100%" stopColor="#ff80ab" stopOpacity={0} />
        </radialGradient>
      </defs>
      <rect x={0} y={0} width={1080} height={1920} fill="#0b2236" opacity={0.25} />
      <g transform={`translate(${shake} ${-40 + 20 * (1 - ease(o))})`}>
        <path d="M 120 1560 L 150 1020 Q 170 900 360 870 L 470 850 L 610 850 L 720 870 Q 910 900 930 1020 L 960 1560 Z" fill="url(#dgCoat)" stroke="#b7c2cf" strokeWidth={5} />
        <path d="M 470 850 L 540 1010 L 610 850" fill="#f1f4f8" stroke="#b7c2cf" strokeWidth={4} />
        <path d={TRAP} fill={trapCol} fillOpacity={red} stroke={trapCol} strokeWidth={6} strokeOpacity={0.9} />
        <rect x={478} y={740} width={124} height={150} rx={40} fill="url(#dgSkin)" stroke="#d79d72" strokeWidth={4} />
        <ellipse cx={540} cy={610} rx={125} ry={150} fill="url(#dgSkin)" stroke="#d79d72" strokeWidth={4} />
        <path d="M 412 600 Q 400 470 540 452 Q 690 450 670 600 Q 650 520 560 515 Q 470 515 430 560 Z" fill="#1f1712" />
        <ellipse cx={418} cy={630} rx={18} ry={32} fill="#e0a87c" />
        <ellipse cx={662} cy={630} rx={18} ry={32} fill="#e0a87c" />
        <ellipse cx={495} cy={622} rx={11} ry={8} fill="#2b1d14" />
        <ellipse cx={585} cy={622} rx={11} ry={8} fill="#2b1d14" />
        <path d={ph === 'tense' ? 'M 505 705 Q 540 695 575 705' : 'M 505 700 Q 540 718 575 700'} stroke="#b05f55" strokeWidth={6} fill="none" strokeLinecap="round" />
        {ph === 'tense' && <path d="M 470 590 L 515 600 M 565 600 L 610 590" stroke="#2b1d14" strokeWidth={6} strokeLinecap="round" />}
        {(ph === 'brain' || ph === 'calm') && <ellipse cx={540} cy={545} rx={115} ry={85} fill="url(#dgBrain)" opacity={ph === 'brain' ? 0.6 + 0.4 * pulse : 0.5} />}
        {ph === 'tense' &&
          [-1, 1].map((sd) => (
            <path key={sd} d={`M ${540 + sd * 150} 880 l ${sd * 30} -22 l ${sd * 30} 22 l ${sd * 30} -22 l ${sd * 30} 22`} stroke="#fff" strokeWidth={7} fill="none" strokeLinejoin="round" opacity={0.6 + 0.4 * pulse} />
          ))}
        {dots}
        {ph === 'calm' &&
          [0, 1, 2].map((i) => {
            const u = (((t * 0.5 + i / 3) % 1) + 1) % 1;
            return <ellipse key={i} cx={540} cy={600} rx={150 + 220 * u} ry={180 + 220 * u} fill="none" stroke="#81d4fa" strokeWidth={8} opacity={1 - u} />;
          })}
        <g opacity={ramp(t, a + 0.6, a + 1.0)}>
          <line x1={800} y1={935} x2={880} y2={1100} stroke="#fff" strokeWidth={5} />
          <rect x={760} y={1100} width={260} height={66} rx={33} fill={trapCol} stroke="#fff" strokeWidth={4} />
          <text x={890} y={1146} textAnchor="middle" fontFamily={FONT} fontSize={38} fill="#fff">
            CƠ THANG
          </text>
        </g>
      </g>
    </svg>
  );
};

export const D78: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const ex = [...D.ex].reverse().find((e) => t >= e.start);
  const dg = D.diagram.find((c) => t >= c.t && t < c.e);
  const cue = dg ? undefined : D.cues.find((c) => t >= c.t && t < c.e) ?? D.demo.find((c) => t >= c.t && t < c.e);
  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      <OffthreadVideo src={staticFile('d78.mp4')} muted />
      <Diagram t={t} f={f} />
      {cue && <BodyFx t={t} f={f} c={cue} />}
      {cue && <Panel t={t} c={cue} />}
      {dg && <Panel t={t} c={dg} />}
      {ex && <Chip ex={ex} t={t} />}
    </AbsoluteFill>
  );
};
