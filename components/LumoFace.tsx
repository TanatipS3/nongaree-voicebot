'use client';

import { forwardRef, useImperativeHandle } from 'react';

export type FaceMode = 'idle' | 'happy' | 'sad' | 'angry' | 'wow' | 'sleep';
export type GazeState = 'idle' | 'user_talking' | 'agent_thinking' | 'agent_talking';

export interface LumoFaceHandle {
    setMode: (mode: FaceMode) => void;
    setAmplitude: (rms: number) => void;
    setGazeState: (state: GazeState) => void;
}

interface Props {
    mode?: FaceMode;
}

const AVATAR_SRC = '/avatar/aree_cutout.png';

const LumoFace = forwardRef<LumoFaceHandle, Props>((_props, ref) => {
    useImperativeHandle(ref, () => ({
        setMode: () => {},
        setAmplitude: () => {},
        setGazeState: () => {},
    }), []);

    return (
        <div
            style={{
                position: 'relative',
                width: '100%',
                lineHeight: 0,
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
            }}
        >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
                src={AVATAR_SRC}
                alt="Aree"
                draggable={false}
                style={{
                    display: 'block',
                    width: '100%',
                    maxWidth: 520,
                    height: 'auto',
                    borderRadius: 0,
                    objectFit: 'contain',
                }}
            />
        </div>
    );
});

LumoFace.displayName = 'LumoFace';

export default LumoFace;
