import { C } from '../../config/colors';

export default function LiveDot({ color, idle = false }) {
  const dotColor = idle ? C.txtM : (color || C.acc);
  return (
    <span style={{
      display: 'inline-block',
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: dotColor,
      boxShadow: idle ? 'none' : `0 0 6px ${dotColor}88`,
      animation: idle ? 'none' : 'mf-pulse 1.5s ease-in-out infinite',
      flexShrink: 0,
    }} />
  );
}
