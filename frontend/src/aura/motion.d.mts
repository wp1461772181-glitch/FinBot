export interface BodyMotion { dx: number; tilt: number; scale: number }
export const REST: Readonly<BodyMotion>;
export function dart(age: number): number;
export function bodyMotion(input: { variant: string | null | undefined; phase: string; real?: number; ages?: ReadonlyArray<number>; reduced?: boolean }): BodyMotion;
