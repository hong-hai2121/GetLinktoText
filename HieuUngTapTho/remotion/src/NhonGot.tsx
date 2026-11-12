import React from 'react';
import {
  AbsoluteFill,
  Easing,
  OffthreadVideo,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

// ---- Mốc theo lời nói (giây, từ Whisper) ----
// 0.00 "Động tác số 6 là nhón gót khoảng 10 lần"
// 2.16 "Cô anh chị mình đứng vịn vào lưng ghế"
// 4.16 "Nhón gót lên cao"
// 5.44 "Rồi giữ 1 giây"
// 6.46 "Sau đó hạ thật chậm"
const FPS = 30;
const s = (sec: number) => Math.round(sec * FPS);

const STEPS = [
  {from: 0, label: 'NHÓN GÓT', sub: 'KHOẢNG 10 LẦN'},
  {from: s(2.16), label: 'ĐỨNG VỊN LƯNG GHẾ', sub: ''},
  {from: s(4.16), label: 'NHÓN GÓT LÊN CAO', sub: ''},
  {from: s(5.44), label: 'GIỮ 1 GIÂY', sub: ''},
  {from: s(6.46), label: 'HẠ GÓT THẬT CHẬM', sub: ''},
];

const FONT = "'Segoe UI Black', 'Segoe UI', sans-serif";
const C = {
  teal: '#0b7a75',
  tealDark: '#06514e',
  orange: '#ff7a00',
  shirt: '#1e88e5',
  shirtDark: '#1565c0',
  pants: '#37474f',
  pantsFar: '#263238',
  skin: '#f2c18d',
  skinDark: '#d9a26b',
  hair: '#2b2118',
  shoe: '#ff7043',
  shoeFar: '#d84315',
  wood: '#8d6e63',
  woodDark: '#6d4c41',
};

type P = {x: number; y: number};
const add = (a: P, b: P): P => ({x: a.x + b.x, y: a.y + b.y});
const lerpP = (a: P, b: P, t: number): P => ({x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t});
const rot = (v: P, th: number): P => ({
  x: v.x * Math.cos(th) - v.y * Math.sin(th),
  y: v.x * Math.sin(th) + v.y * Math.cos(th),
});

// Khớp 2 đoạn (vai -> khuỷu -> bàn tay), khuỷu gập xuống dưới.
const ik = (sh: P, hand: P, l1: number, l2: number): {elbow: P; hand: P} => {
  const dx = hand.x - sh.x;
  const dy = hand.y - sh.y;
  let d = Math.hypot(dx, dy);
  const maxD = l1 + l2 - 0.5;
  let h = hand;
  if (d > maxD) {
    h = {x: sh.x + (dx / d) * maxD, y: sh.y + (dy / d) * maxD};
    d = maxD;
  }
  const a = Math.atan2(dy, dx);
  const cosA = Math.min(1, Math.max(-1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)));
  const alpha = Math.acos(cosA);
  const elbow = {x: sh.x + l1 * Math.cos(a + alpha), y: sh.y + l1 * Math.sin(a + alpha)};
  return {elbow, hand: h};
};

const line = (a: P, b: P, color: string, w: number, key?: string) => (
  <line key={key} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={color} strokeWidth={w} strokeLinecap="round" />
);

// ---- Người tập nhìn nghiêng (quay sang phải), đứng cạnh ghế ----
const GROUND = 620;
const BALL: P = {x: 360, y: GROUND}; // ức bàn chân: tâm xoay khi nhón gót
const MAX_TILT = (36 * Math.PI) / 180;

const Foot: React.FC<{ball: P; th: number; color: string}> = ({ball, th, color}) => {
  // Mũi chân nằm phẳng trên sàn; phần còn lại xoay quanh ức bàn chân.
  const heel = add(ball, rot({x: -74, y: 0}, th));
  const heelTop = add(ball, rot({x: -70, y: -30}, th));
  const ankle = add(ball, rot({x: -46, y: -38}, th));
  const instep = add(ball, rot({x: -10, y: -22}, th));
  const toe = {x: ball.x + 34, y: ball.y};
  const toeTop = {x: ball.x + 30, y: ball.y - 14};
  const d = `M ${heel.x} ${heel.y} L ${ball.x} ${ball.y} L ${toe.x} ${toe.y} Q ${toe.x + 4} ${toeTop.y} ${toeTop.x} ${toeTop.y}
    L ${instep.x} ${instep.y} L ${ankle.x} ${ankle.y} L ${heelTop.x} ${heelTop.y} Q ${heel.x - 8} ${heel.y - 10} ${heel.x} ${heel.y} Z`;
  return <path d={d} fill={color} stroke="#00000022" strokeWidth={2} strokeLinejoin="round" />;
};

const Figure: React.FC<{lift: number; reach: number; glowChair: number; glowFoot: number}> = ({
  lift,
  reach,
  glowChair,
  glowFoot,
}) => {
  const th = lift * MAX_TILT;
  const ankle0 = add(BALL, {x: -46, y: -38});
  const ankle = add(BALL, rot({x: -46, y: -38}, th));
  const D = {x: ankle.x - ankle0.x, y: ankle.y - ankle0.y};
  const mv = (p: P) => add(p, D);

  const hip = mv({x: 318, y: 352});
  const knee = mv({x: 324, y: 470});
  const shoulder = mv({x: 330, y: 196});
  const head = mv({x: 338, y: 132});

  // Bàn tay: buông xuôi -> đặt lên thanh tựa lưng ghế
  const chairHand: P = {x: 470, y: 330};
  const hang = add(shoulder, {x: 14, y: 210});
  const handT = lerpP(hang, chairHand, reach);
  const near = ik(shoulder, handT, 112, 110);
  const shFar = add(shoulder, {x: -8, y: 6});
  const far = ik(shFar, lerpP(add(shFar, {x: 10, y: 208}), {x: 478, y: 334}, reach), 112, 110);

  const farOff = {x: -10, y: 0};
  const ballFar = add(BALL, farOff);
  const ankleFar = add(ankle, farOff);
  const kneeFar = add(knee, farOff);
  const hipFar = add(hip, {x: -6, y: 0});

  return (
    <g>
      {/* bóng dưới chân */}
      <ellipse cx={330} cy={GROUND + 6} rx={110 - lift * 22} ry={10} fill="#00000022" />
      {/* sàn */}
      <line x1={120} y1={GROUND + 2} x2={760} y2={GROUND + 2} stroke="#b0bec5" strokeWidth={5} strokeLinecap="round" />

      {/* GHẾ (nhìn nghiêng) */}
      <g>
        {glowChair > 0 && (
          <circle cx={chairHand.x + 4} cy={chairHand.y + 6} r={34 + glowChair * 10} fill={C.orange} opacity={0.28 * glowChair} />
        )}
        {line({x: 480, y: 330}, {x: 480, y: GROUND}, C.woodDark, 16)}
        {line({x: 640, y: 456}, {x: 640, y: GROUND}, C.woodDark, 16)}
        {line({x: 472, y: 456}, {x: 652, y: 456}, C.wood, 22)}
        {line({x: 480, y: 340}, {x: 480, y: 452}, C.wood, 22)}
        <rect x={462} y={316} width={36} height={22} rx={8} fill={C.wood} />
      </g>

      {/* tay xa (sau thân) */}
      {line(shFar, far.elbow, C.shirtDark, 30)}
      {line(far.elbow, far.hand, C.skinDark, 24)}

      {/* chân xa */}
      <Foot ball={ballFar} th={th} color={C.shoeFar} />
      {line(hipFar, kneeFar, C.pantsFar, 42)}
      {line(kneeFar, ankleFar, C.skinDark, 30)}

      {/* chân gần */}
      {line(hip, knee, C.pants, 44)}
      {line(knee, add(ankle, {x: 0, y: -6}), C.skin, 32)}
      <Foot ball={BALL} th={th} color={C.shoe} />

      {/* thân */}
      {line(add(hip, {x: 0, y: -6}), add(shoulder, {x: 0, y: 14}), C.shirt, 84)}
      {line(add(hip, {x: -2, y: -4}), add(hip, {x: 2, y: 8}), C.pants, 72)}
      {/* cổ + đầu */}
      {line(add(shoulder, {x: 2, y: -4}), add(head, {x: 0, y: 30}), C.skin, 26)}
      <circle cx={head.x} cy={head.y} r={44} fill={C.skin} />
      <path
        d={`M ${head.x - 46} ${head.y + 6} Q ${head.x - 50} ${head.y - 52} ${head.x + 4} ${head.y - 48}
            Q ${head.x + 42} ${head.y - 46} ${head.x + 44} ${head.y - 14}
            Q ${head.x + 10} ${head.y - 26} ${head.x - 8} ${head.y - 8}
            Q ${head.x - 20} ${head.y + 14} ${head.x - 32} ${head.y + 30} Z`}
        fill={C.hair}
      />
      <circle cx={head.x - 4} cy={head.y + 4} r={9} fill={C.skinDark} />
      <circle cx={head.x + 26} cy={head.y - 2} r={4.5} fill="#2b2118" />
      <path d={`M ${head.x + 22} ${head.y + 20} Q ${head.x + 32} ${head.y + 26} ${head.x + 40} ${head.y + 18}`} stroke="#9c5a3c" strokeWidth={4} fill="none" strokeLinecap="round" />

      {/* tay gần */}
      {line(shoulder, near.elbow, C.shirt, 32)}
      {line(near.elbow, near.hand, C.skin, 26)}
      <circle cx={near.hand.x} cy={near.hand.y} r={15} fill={C.skin} />

      {/* vòng sáng ở gót */}
      {glowFoot > 0 && (
        <circle
          cx={BALL.x - 40}
          cy={GROUND - 26}
          r={70}
          fill="none"
          stroke={C.orange}
          strokeWidth={6}
          strokeDasharray="14 10"
          opacity={glowFoot}
        />
      )}
    </g>
  );
};

// Ô soi cận bàn chân: thấy rõ gót rời sàn
const FootZoom: React.FC<{lift: number; opacity: number}> = ({lift, opacity}) => {
  const th = lift * MAX_TILT;
  const ankle = add(BALL, rot({x: -46, y: -38}, th));
  const heel = add(BALL, rot({x: -74, y: 0}, th));
  const k = 1.75;
  const c = {x: BALL.x - 24, y: GROUND - 22};
  const R = 84;
  const gap = GROUND - heel.y;
  return (
    <g transform="translate(750 478)" opacity={opacity}>
      <defs>
        <clipPath id="zoomClip">
          <circle r={R} />
        </clipPath>
      </defs>
      <circle r={R} fill="#f5f9f9" />
      <g clipPath="url(#zoomClip)">
        <g transform={`scale(${k}) translate(${-c.x} ${-c.y})`}>
          <rect x={c.x - 80} y={GROUND + 2} width={160} height={40} fill="#cfd8dc" />
          {line(add(ankle, {x: 0, y: -4}), add(ankle, {x: 10, y: -120}), C.skin, 32)}
          <Foot ball={BALL} th={th} color={C.shoe} />
          {gap > 3 && (
            <g>
              <line x1={heel.x - 4} y1={GROUND} x2={heel.x - 4} y2={heel.y + 3} stroke={C.orange} strokeWidth={3} />
              <line x1={heel.x - 12} y1={GROUND} x2={heel.x + 4} y2={GROUND} stroke={C.orange} strokeWidth={3} />
            </g>
          )}
        </g>
      </g>
      <circle r={R} fill="none" stroke={C.orange} strokeWidth={7} />
      <text y={R + 40} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={30} fill={C.tealDark}>
        {gap > 3 ? 'GÓT RỜI SÀN' : 'GÓT CHẠM SÀN'}
      </text>
    </g>
  );
};

// Mũi tên lên / xuống
const Arrow: React.FC<{x: number; y: number; dir: 'up' | 'down'; opacity: number; color: string; scale?: number}> = ({
  x,
  y,
  dir,
  opacity,
  color,
  scale = 1,
}) => (
  <g transform={`translate(${x} ${y}) scale(${scale}) ${dir === 'down' ? 'rotate(180)' : ''}`} opacity={opacity}>
    <path d="M 0 -60 L 34 -14 L 13 -14 L 13 50 L -13 50 L -13 -14 L -34 -14 Z" fill={color} stroke="#fff" strokeWidth={5} strokeLinejoin="round" />
  </g>
);

export const NhonGot: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // ---- Biến chuyển động ----
  const reach = interpolate(frame, [s(2.8), s(3.8)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });
  const up = interpolate(frame, [s(4.25), s(5.15)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
  const down = interpolate(frame, [s(6.6), s(7.85)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.sin),
  });
  const lift = up * (1 - down);

  const stepIdx = STEPS.reduce((acc, st, i) => (frame >= st.from ? i : acc), 0);
  const step = STEPS[stepIdx];
  const stepIn = spring({frame: frame - step.from, fps, config: {damping: 14, stiffness: 160}});

  const cardIn = spring({frame: frame - 3, fps, config: {damping: 16, stiffness: 120}});
  const topIn = spring({frame: frame - 1, fps, config: {damping: 14, stiffness: 140}});

  const glowChair = stepIdx === 1 ? 0.6 + 0.4 * Math.sin(frame / 4) : 0;
  const glowFoot = stepIdx >= 2 && stepIdx <= 4 ? 0.85 : 0;

  // Đồng hồ giữ 1 giây
  const hold = interpolate(frame, [s(5.6), s(6.5)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const holdOpacity =
    interpolate(frame, [s(5.44), s(5.6)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) *
    interpolate(frame, [s(6.5), s(6.7)], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  const upArrowOp =
    interpolate(frame, [s(4.16), s(4.35)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) *
    interpolate(frame, [s(5.3), s(5.5)], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const upArrowY = 470 - 40 * up;
  const downArrowOp = interpolate(frame, [s(6.46), s(6.65)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const downArrowY = 420 + 50 * down;

  const zoomOp = interpolate(frame, [s(4.16), s(4.4)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  // ×10 lúc mở đầu
  const tenOp =
    interpolate(frame, [s(1.6), s(1.9)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) *
    interpolate(frame, [s(2.6), s(2.9)], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const tenScale = spring({frame: frame - s(1.6), fps, config: {damping: 9, stiffness: 180}});

  const CARD = {x: 40, y: 1000, w: 1000, h: 860};

  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      <OffthreadVideo src={staticFile('1.mp4')} />

      {/* Thẻ tiêu đề trên cùng */}
      <div
        style={{
          position: 'absolute',
          left: 40,
          right: 40,
          top: 60,
          display: 'flex',
          justifyContent: 'center',
          transform: `translateY(${(1 - topIn) * -160}px)`,
          opacity: topIn,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 22,
            background: C.teal,
            borderRadius: 28,
            padding: '18px 38px 18px 18px',
            boxShadow: '0 10px 30px rgba(0,0,0,0.35)',
            border: '5px solid white',
          }}
        >
          <div
            style={{
              background: C.orange,
              color: 'white',
              fontFamily: FONT,
              fontWeight: 900,
              fontSize: 40,
              borderRadius: 18,
              padding: '8px 20px',
            }}
          >
            ĐỘNG TÁC 6
          </div>
          <div style={{color: 'white', fontFamily: FONT, fontWeight: 900, fontSize: 58, letterSpacing: 1}}>NHÓN GÓT</div>
        </div>
      </div>

      {/* Thẻ minh họa động tác, đè lên phần thân dưới */}
      <div
        style={{
          position: 'absolute',
          left: CARD.x,
          top: CARD.y,
          width: CARD.w,
          height: CARD.h,
          borderRadius: 44,
          background: 'white',
          boxShadow: '0 18px 50px rgba(0,0,0,0.40)',
          border: `6px solid ${C.teal}`,
          overflow: 'hidden',
          transform: `translateY(${(1 - cardIn) * 1000}px)`,
        }}
      >
        {/* Đầu thẻ: bước hiện tại */}
        <div
          style={{
            height: 150,
            background: C.teal,
            display: 'flex',
            alignItems: 'center',
            padding: '0 34px',
            gap: 26,
          }}
        >
          <div
            style={{
              width: 92,
              height: 92,
              borderRadius: 46,
              background: stepIdx === 0 ? C.orange : 'white',
              color: stepIdx === 0 ? 'white' : C.teal,
              fontFamily: FONT,
              fontWeight: 900,
              fontSize: stepIdx === 0 ? 40 : 56,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transform: `scale(${0.6 + 0.4 * stepIn})`,
              flexShrink: 0,
            }}
          >
            {stepIdx === 0 ? '×10' : stepIdx}
          </div>
          <div
            style={{
              flex: 1,
              opacity: stepIn,
              transform: `translateX(${(1 - stepIn) * 60}px)`,
            }}
          >
            <div style={{color: 'white', fontFamily: FONT, fontWeight: 900, fontSize: 60, lineHeight: 1.05}}>
              {step.label}
            </div>
            {step.sub ? (
              <div style={{color: '#ffe0b2', fontFamily: FONT, fontWeight: 900, fontSize: 38}}>{step.sub}</div>
            ) : null}
          </div>
          {/* chấm tiến độ 4 bước */}
          <div style={{display: 'flex', gap: 12}}>
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 11,
                  background: i <= stepIdx ? C.orange : 'rgba(255,255,255,0.35)',
                  border: '3px solid white',
                }}
              />
            ))}
          </div>
        </div>

        {/* Hình minh họa */}
        <svg width={CARD.w - 12} height={CARD.h - 162} viewBox="110 70 720 560" style={{display: 'block'}}>
          <Figure lift={lift} reach={reach} glowChair={glowChair} glowFoot={glowFoot} />

          {/* mũi tên nhón lên cạnh gót */}
          <Arrow x={185} y={upArrowY} dir="up" opacity={upArrowOp} color={C.orange} scale={0.9} />
          {/* mũi tên hạ chậm */}
          <Arrow x={185} y={downArrowY} dir="down" opacity={downArrowOp * (1 - 0.35 * Math.max(0, Math.sin(frame / 5)))} color={C.teal} scale={0.9} />
          {downArrowOp > 0 && (
            <text x={185} y={570} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={34} fill={C.teal} opacity={downArrowOp}>
              CHẬM
            </text>
          )}

          {/* soi cận bàn chân */}
          <FootZoom lift={lift} opacity={zoomOp} />

          {/* đồng hồ giữ 1 giây */}
          {holdOpacity > 0 && (
            <g transform="translate(730 200)" opacity={holdOpacity}>
              <circle r={78} fill="white" stroke="#e0e0e0" strokeWidth={14} />
              <circle
                r={78}
                fill="none"
                stroke={C.orange}
                strokeWidth={14}
                strokeLinecap="round"
                strokeDasharray={`${2 * Math.PI * 78 * hold} ${2 * Math.PI * 78}`}
                transform="rotate(-90)"
              />
              <text y={20} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={60} fill={C.tealDark}>
                1s
              </text>
              <text y={128} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={34} fill={C.tealDark}>
                GIỮ
              </text>
            </g>
          )}

          {/* ×10 lúc mở đầu */}
          {tenOp > 0 && (
            <g transform={`translate(730 210) scale(${tenScale})`} opacity={tenOp}>
              <circle r={92} fill={C.orange} stroke="white" strokeWidth={8} />
              <text y={22} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={68} fill="white">
                ×10
              </text>
              <text y={140} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={32} fill={C.tealDark}>
                LẦN
              </text>
            </g>
          )}
        </svg>
      </div>
    </AbsoluteFill>
  );
};
