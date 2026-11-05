// SPDX-License-Identifier: GPL-2.0-only
/* Diagnostic experiment: real software player, synthetic native clock and USB sink.
 * The USB frame clock deliberately differs from the host/native observation clock.
 * Reports independent completed-source phase; it does not certify real hardware. */
#define main retained_player_main
#include "../test_extra_player.c"
#undef main

static void skew_advance(unsigned ms, double scale) {
 for (unsigned t=0; t<ms; t+=10) {
  clock_ms+=10;
  consume(0,441.*scale); consume(1,441.*scale);
  step();
 }
}

static xz_usb_result skew_position(void *ctx,uint32_t epoch,xz_usb_position *out){
 xz_usb_result result=fake_position(ctx,epoch,out);
 if(result==XZ_USB_OK)out->wire_observed_us=(uint64_t)clock_ms*1000u;
 return result;
}

static double skew_error(unsigned deck, double scale) {
 const xz_usb_deck_position *q=&f.position.deck[deck];
 /* Independent oracle uses the injected hardware rate, not the player's estimator. */
 double source_phase=((double)q->source_after_completed/debug((int)deck).source_rate-.1)*2.;
 double age=(f.wire[deck]-(double)q->source_completed_wire_frame)/(XZ_USB_RATE*scale);
 uint64_t at=(uint64_t)llround((double)clock_ms*1000.-age*1000000.-sim_native.output_latency_us);
 double error=fmod(source_phase-sim_native_phase_at_us(at)+.5,1.);
 if(error<0)error+=1.;
 return (error-.5)/(sim_native.bpm/60.);
}

static void probe(int ppm, unsigned source, unsigned duration) {
 clock_ms=1000;wire_horizon=882;
 position_interval=position_noise=position_blocked=threaded_clock=0;
 struct xz_xp_env env={{NULL,fake_link,fake_submit,fake_flush,skew_position,fake_transition},
  now_ms,sync_resolve,master_bpm,NULL,NULL,0,1};
 p=xz_xp_create(&env);assert(p);xz_xp_set_native_sync_clock(p,copy_sim_native);
 fake_route(997);step();sync_loop_track(0,source,350);
 sim_native=(__typeof__(sim_native)){.active=1,.native_deck=0,.playing=1,
  .source_revision=21,.track_identity=0x32000,.uncertainty_us=120,.obs_age_us=12350,
  .output_latency_us=4500,.bpm=126.,.anchor_us=(uint64_t)clock_ms*1000u,.anchor_phase=.25};
 press(0,XZ_EXTRA_IN_SYNC);
 double scale=1.+ppm/1000000.,initial=0,final=0,maximum=0;
 unsigned locked=0,samples=0;
 for(unsigned t=0;t<duration;t+=10){
  skew_advance(10,scale);
  if(t<5000)continue;
  final=skew_error(0,scale);
  if(!samples)initial=final;
  if(fabs(final)>maximum)maximum=fabs(final);
  locked+=!!view.deck[0].sync.locked;samples++;
 }
 printf("{\"usb_clock_ppm\":%d,\"source_rate\":%u,\"duration_ms\":%u,"
        "\"initial_error_us\":%.3f,\"final_error_us\":%.3f,\"max_error_us\":%.3f,"
        "\"reported_locked_samples\":%u,\"samples\":%u,\"hardware\":false}\n",
        ppm,debug(0).source_rate,duration,initial*1e6,final*1e6,maximum*1e6,locked,samples);
 fflush(stdout);
 assert(maximum<.001); /* Unequal clocks must not report lock while drifting apart. */
 xz_xp_destroy(p);p=NULL;
}

int main(int argc,char **argv){
 assert(argc==2);assert(!pthread_mutex_init(&f.lock,NULL));
 snprintf(fixtures,sizeof fixtures,"%s",argv[1]);snprintf(anlz_dir,sizeof anlz_dir,"%s/anlz",argv[1]);build_analysis();
 const int ppm[]={0,-250,250,-1000,1000};
 for(unsigned rate=1;rate<=2;rate++)for(unsigned i=0;i<sizeof ppm/sizeof *ppm;i++)probe(ppm[i],rate,90000);
 pthread_mutex_destroy(&f.lock);return 0;
}
