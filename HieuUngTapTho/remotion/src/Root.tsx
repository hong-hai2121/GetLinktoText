import React from 'react';
import {Composition} from 'remotion';
import {NhonGot} from './NhonGot';

import {ThuGian} from './ThuGian';
import {Lung01, LUNG01_FRAMES} from './Lung01';
import {Lung02, LUNG02_FRAMES} from './Lung02';
import {CoGay, COGAY_FRAMES} from './CoGay';
import {CoGay2, COGAY2_FRAMES} from './CoGay2';

// Video gốc 1.mov: 1080x1920, 30 fps, 7.92 s (238 khung)
// Thư giãn cơ tiến triển: 334 s (10020 khung)
export const Root: React.FC = () => (
  <>
    <Composition id="NhonGot" component={NhonGot} durationInFrames={238} fps={30} width={1080} height={1920} />
    <Composition id="CoGay2" component={CoGay2} durationInFrames={COGAY2_FRAMES} fps={30} width={1080} height={1920} />
    <Composition id="CoGay" component={CoGay} durationInFrames={COGAY_FRAMES} fps={30} width={1080} height={1920} />
    <Composition id="Lung02" component={Lung02} durationInFrames={LUNG02_FRAMES} fps={30} width={1080} height={1920} />
    <Composition id="Lung01" component={Lung01} durationInFrames={LUNG01_FRAMES} fps={30} width={1080} height={1920} />
    <Composition id="ThuGian" component={ThuGian} durationInFrames={10020} fps={30} width={1080} height={1920} />
  </>
);
