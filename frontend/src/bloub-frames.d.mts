export const SETTLE: number;
export interface FrameInputs { state: string; hovered?: boolean; aiming?: boolean }
export function frameDemand(input: FrameInputs): boolean;
export function needsFrames(input: FrameInputs & { quietFor?: number }): boolean;
