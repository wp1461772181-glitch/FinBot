import type { AuraInput, AuraPrim } from "./shared.mjs";
export declare const LEAVE_LEN: number;
export declare const ENTER_LEN: number;
export declare const isHandoffPhase: (phase: string) => boolean;
export declare const familyOf: (variant: string) => "dial" | "speed" | "ticker" | "halo" | "page" | "dots" | "reticle";
export interface BodyPose { dx: number; dy: number; tilt: number; scale: number; sx: number; alpha: number }
export declare function handoffBody(options: { from: string; to: string | null; age: number; quiet?: boolean; carry?: Partial<BodyPose> | null }): BodyPose;
export declare function handoffAura(family: string, input: AuraInput, rest: (over: Partial<AuraInput>) => AuraPrim[]): AuraPrim[] | null;
