export function captureArgs(display, video, progress) {
  return [
    "-nostdin", "-y", "-loglevel", "info", "-stats_period", "0.2", "-progress", progress,
    "-f", "x11grab", "-draw_mouse", "0", "-framerate", "30", "-video_size", "1280x800",
    "-use_wallclock_as_timestamps", "1", "-i", display,
    "-copyts", "-fps_mode", "passthrough", "-c:v", "ffv1", "-level", "3", "-threads", "2",
    "-pix_fmt", "bgr0", "-enc_time_base", "1:1000", "-avoid_negative_ts", "disabled", video,
  ];
}
