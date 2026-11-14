// The sidebar and login brand mark: the three newspaper-reading poses (public/logo*.svg) crossfading in a random order.
import { useEffect, useState } from "react";
import { nextPose } from "../../orb.mjs";

const BRAND_POSES = ["logo.svg", "logo-peek.svg", "logo-3d.svg"];

/** The brand mark: tilt / peek / 3-quarter poses, each held 4-8 s, the next picked at random, 600 ms crossfade.
 * Reduced motion: the tilt pose stays. */
export function BrandLogo() {
  const [pose, setPose] = useState(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let timer = 0;
    const tick = () => { timer = window.setTimeout(() => { if (document.visibilityState !== "hidden") setPose(p => nextPose(p, BRAND_POSES.length)); tick(); }, 4000 + Math.random() * 4000); };
    tick();
    return () => window.clearTimeout(timer);
  }, []);
  return <span className="brand-logo" aria-hidden="true">
    {BRAND_POSES.map((src, i) => <img key={src} src={`${import.meta.env.BASE_URL}${src}`} alt="" className={i === pose ? "is-on" : undefined} />)}
  </span>;
}
