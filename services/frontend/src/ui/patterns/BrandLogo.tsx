import { cn } from '@/lib/cn';
import { useBrand } from '@/app/providers/brand';
import { useTheme } from '@/app/providers/theme';
import ssfLogoPaths from '@/ui/assets/ssfLogoPaths';
import kasselWhite from '@/ui/assets/kassel-dialog-white.png';
import kasselBlack from '@/ui/assets/kassel-dialog-black.png';

interface BrandLogoProps {
  className?: string;
}

/**
 * The SSF mark is inline SVG so it inherits the theme foreground; the Kassel
 * mark ships as one PNG per theme, exactly as the export does. All 18 paths
 * share currentColor with no opacity, so their paint order is immaterial.
 */
export function BrandLogo({ className }: BrandLogoProps) {
  const { brand, displayName } = useBrand();
  const { theme } = useTheme();

  if (brand === 'kassel') {
    return (
      <img
        src={theme === 'dark' ? kasselWhite : kasselBlack}
        alt={displayName}
        className={cn('h-8 object-contain', className)}
      />
    );
  }

  return (
    <svg
      className={cn('h-[46px] w-[107px]', className)}
      viewBox="0 0 106.566 46"
      fill="none"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={displayName}
    >
      {Object.entries(ssfLogoPaths).map(([key, d]) => (
        <path key={key} d={d} fill="currentColor" />
      ))}
    </svg>
  );
}
