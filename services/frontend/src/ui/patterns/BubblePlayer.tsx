import { Pause, Play } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useClipPeaks, usePlayback } from '@/app/providers/playback';
import { BAR_COUNT, activeBarsForProgress } from '@/core/audio/waveform';
import { Waveform } from './Waveform';

interface BubblePlayerProps {
  messageId: string;
  audioUrl: string;
}

/**
 * The play control and waveform for one incoming message.
 *
 * Playback belongs to the conversation, not the bubble: only one clip is ever
 * audible and arrivals play themselves, so the state lives in `PlaybackProvider`
 * and this follows it. A clip that autoplayed therefore shows pause without ever
 * having been tapped, which is the whole reason the button reads `playingId`
 * rather than keeping a flag of its own.
 */
export function BubblePlayer({ messageId, audioUrl }: Readonly<BubblePlayerProps>) {
  const { t } = useTranslation();
  const { playingId, progress, paused, completedIds, playNow, pause, resume } = usePlayback();
  const peaks = useClipPeaks(audioUrl);

  const isPlaying = playingId === messageId;
  const isAudible = isPlaying && !paused;

  /**
   * The waveform draws itself as the clip plays and stays solid once it has
   * been heard: there is no idle track behind it, which is why an unplayed
   * message shows an empty row. Both come from the export — its bars are
   * painted the bubble's own colour until they fill (export 1207), and its
   * animation stops on the last bar without resetting the count (export 1212).
   */
  const activeBars = (() => {
    if (isPlaying) {
      return activeBarsForProgress(progress);
    }
    return completedIds.has(messageId) ? BAR_COUNT : 0;
  })();

  const press = () => {
    if (isAudible) {
      pause();
    } else if (isPlaying) {
      resume();
    } else {
      playNow(messageId, audioUrl);
    }
  };

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={press}
        aria-label={isAudible ? t('conversation.pause') : t('conversation.play')}
        className="flex size-9 shrink-0 items-center justify-center rounded-full border border-border-play text-fg-consent transition-colors duration-150"
      >
        {isAudible ? (
          <Pause data-icon="pause" size={15} strokeWidth={2} />
        ) : (
          <Play data-icon="play" size={15} strokeWidth={2} />
        )}
      </button>

      <div className="flex-1">
        <Waveform activeBars={activeBars} barColorClass="bg-accent" heights={peaks} />
      </div>
    </div>
  );
}
