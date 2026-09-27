export function captureArgs(input, video, progress, fps = 30) {
  return [
    "-nostdin", "-y", "-loglevel", "info", "-stats_period", "0.2", "-progress", progress,
    "-f", "x11grab", "-draw_mouse", "0", "-framerate", String(fps), "-video_size", "1280x800",
    "-use_wallclock_as_timestamps", "1", "-i", input,
    "-copyts", "-fps_mode", "passthrough", "-c:v", "ffv1", "-level", "3", "-threads", "2",
    "-pix_fmt", "bgr0", "-enc_time_base", "1:1000", "-avoid_negative_ts", "disabled", video,
  ];
}
