// Minimal WebView2 host. about:blank, nothing else. Env: CONTROL_ARGS = additional browser args (set but empty = WebView2 runtime defaults),
// CONTROL_PROFILE = user-data folder (throw-away).
use std::path::PathBuf;
use tao::{event::{Event, WindowEvent}, event_loop::{ControlFlow, EventLoop}, window::WindowBuilder};
use wry::{WebContext, WebViewBuilder, WebViewBuilderExtWindows};

fn main() {
    let el = EventLoop::new();
    let window = WindowBuilder::new().with_title("PV Control WebView2").build(&el).unwrap();
    let mut ctx = WebContext::new(std::env::var("CONTROL_PROFILE").ok().map(PathBuf::from));
    let mut b = WebViewBuilder::new_with_web_context(&mut ctx).with_url("about:blank");
    // Present (even empty) => passed to WebView2 verbatim. An EMPTY value replaces wry's own default arguments, so C2 really is the runtime default.
    if let Ok(a) = std::env::var("CONTROL_ARGS") {
        b = b.with_additional_browser_args(a);
    }
    let _webview = b.build(&window).unwrap();
    el.run(move |ev, _, cf| {
        *cf = ControlFlow::Wait;
        if let Event::WindowEvent { event: WindowEvent::CloseRequested, .. } = ev { *cf = ControlFlow::Exit; }
    });
}
