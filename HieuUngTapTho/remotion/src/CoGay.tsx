import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import {Check, Fx, FxOne, HoldClock} from './Lung01';
import DATA from './cogay.json';
import SUBS from './cogay_sub.json';

// "Tập cổ gáy.mov" (1080x1920, 30 fps, 586 s)
// - đoạn ngồi nói (đầu + cuối): phụ đề lời nói; tiêu đề trên đỉnh đầu chỉ 10 giây đầu
// - đoạn tập có lời: chữ mô tả động tác + hiệu ứng trên người thật
// - đoạn tập không lời: vẫn có hiệu ứng (mũi tên chuyển động, vầng sáng, đồng hồ giữ 30 giây)
export const COGAY_FRAMES = 17579;
const FPS = 30;

type P = number[];
type Cue = {t: number; e: number; text: string; sub?: string; kind?: string; hold?: number; marks?: P[]; tag?: string; fx?: Fx[]};
type Ex = {n: number; name: string; start: number; end: number; info: string};
const D = DATA as unknown as {cut_in: number; talk_out: number; ex: Ex[]; cues: Cue[]; demo: Cue[]; holds: {t: number; e: number; n: number}[]};
const SUB = SUBS as {t: number; e: number; w: [string, number][]}[];

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

// ---------- tiêu đề 10 giây đầu, phía trên đỉnh đầu ----------
const Title: React.FC<{t: number}> = ({t}) => {
  if (t > 10.2) return null;
  const s = pop(t, 0.2);
  const o = 1 - ramp(t, 9.6, 10.2);
  const shine = ((t * 0.35) % 1.6) - 0.3;
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        top: 70,
        width: 960,
        height: 300,
        borderRadius: 40,
        background: '#ffffff',
        border: '10px solid #1e88e5',
        boxShadow: '0 14px 40px rgba(0,0,0,0.35)',
        transform: `scale(${s}) translateY(${-40 * ramp(t, 9.6, 10.2)}px)`,
        opacity: o,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
      }}
    >
      <div style={{fontFamily: SERIF, fontWeight: 700, fontSize: 90, lineHeight: 1.05, color: '#111', whiteSpace: 'nowrap'}}>BÀI TẬP CỔ VAI GÁY</div>
      <div style={{fontFamily: SERIF, fontWeight: 700, fontSize: 124, lineHeight: 1.05, color: RED}}>
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
  );
};

// ---------- phụ đề lời nói (đoạn ngồi nói) ----------
const Subtitle: React.FC<{t: number}> = ({t}) => {
  const cur = [...SUB].reverse().find((x) => t >= x.t && t < x.e);
  if (!cur) return null;
  const s = 0.9 + 0.1 * ease(ramp(t, cur.t, cur.t + 0.2));
  return (
    <div style={{position: 'absolute', left: 50, right: 50, top: 1440, display: 'flex', justifyContent: 'center', opacity: ramp(t, cur.t, cur.t + 0.12), transform: `scale(${s})`}}>
      <div style={{background: 'rgba(11,34,54,0.82)', borderRadius: 28, padding: '18px 34px', textAlign: 'center', maxWidth: 960, boxShadow: '0 10px 30px rgba(0,0,0,0.35)'}}>
        {cur.w.map(([w, wt], i) => {
          const on = t >= wt;
          const hi = /^[0-9]/.test(w) || w.startsWith('Đức') || w === 'cổ' || w === 'vai' || w === 'gáy';
          return (
            <span key={i} style={{fontFamily: FONT, fontSize: 62, lineHeight: 1.25, color: on ? (hi ? YEL : '#ffffff') : 'rgba(255,255,255,0.45)', display: 'inline-block', marginRight: 15, transform: `translateY(${on ? -4 * (1 - ramp(t, wt, wt + 0.15)) : 0}px)`}}>
              {w}
            </span>
          );
        })}
      </div>
    </div>
  );
};

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
        <div style={{fontFamily: FONT, fontSize: side ? (c.text.length > 22 ? 40 : c.text.length > 16 ? 48 : 58) : c.text.length > 26 ? 44 : c.text.length > 20 ? 52 : 64, color: c.kind === 'no' ? '#ff8a80' : '#ffffff', lineHeight: 1.1, whiteSpace: 'nowrap'}}>{c.text}</div>
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

// ---------- đồng hồ giữ 30 giây (góc trên phải) ----------
const HoldBadge: React.FC<{t: number}> = ({t}) => {
  const h = D.holds.find((x) => t >= x.t && t < x.e);
  if (!h) return null;
  const o = fadeIO(t, h.t, h.e, 0.3);
  const x = clamp((t - h.t) / h.n);
  const left = Math.max(0, Math.ceil(h.n - (t - h.t)));
  const r = 66;
  const cir = 2 * Math.PI * r;
  const done = x >= 1;
  return (
    <svg viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, width: 1080, height: 1920, opacity: o}}>
      <g transform={`translate(950 340) scale(${pop(t, h.t)})`}>
        <circle r={r + 16} fill={NAVY} fillOpacity={0.88} stroke="#fff" strokeWidth={4} />
        <circle r={r} fill="none" stroke="#ffffff33" strokeWidth={12} />
        <circle r={r} fill="none" stroke={done ? '#00e676' : YEL} strokeWidth={12} strokeDasharray={`${cir * (1 - x)} ${cir}`} transform="rotate(-90)" strokeLinecap="round" />
        <text y={done ? 18 : 16} textAnchor="middle" fontFamily={FONT} fontSize={done ? 54 : 56} fill="#fff">
          {done ? '✓' : left}
        </text>
        <text y={r + 54} textAnchor="middle" fontFamily={FONT} fontSize={30} fill={NAVY} stroke="#fff" strokeWidth={8} paintOrder="stroke">
          GIÂY
        </text>
      </g>
    </svg>
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

export const CoGay: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const inEx = t >= D.cut_in && t < D.talk_out;
  const ex = inEx ? [...D.ex].reverse().find((e) => t >= e.start) : undefined;
  const cue = inEx ? D.cues.find((c) => t >= c.t && t < c.e) ?? D.demo.find((c) => t >= c.t && t < c.e) : undefined;
  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      <OffthreadVideo src={staticFile('cogay.mp4')} muted />
      {cue && <BodyFx t={t} f={f} c={cue} />}
      {inEx && <HoldBadge t={t} />}
      {cue && <Panel t={t} c={cue} />}
      {ex && <Chip ex={ex} t={t} />}
      {!inEx && <Subtitle t={t} />}
      <Title t={t} />
    </AbsoluteFill>
  );
};
