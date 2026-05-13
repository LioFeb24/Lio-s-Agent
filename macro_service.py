from pynput import keyboard
import threading
from macro_recorder import record_macro
from macro_player import play_macro
recording = False
stop_recording = keyboard.Key.esc
macro_file = 'macro.json'

def on_press_f8():
    global recording
    if not recording:
        recording = True
        print('Recording started. Press ESC to stop.')
        threading.Thread(target=record_macro, args=(macro_file, stop_recording), daemon=True).start()

def on_press_f9():
    if not recording:
        print('Playing macro...')
        threading.Thread(target=play_macro, args=(macro_file,), daemon=True).start()
    else:
        print('Cannot play while recording.')

def on_press(key):
    try:
        if key == keyboard.Key.f8:
            on_press_f8()
        elif key == keyboard.Key.f9:
            on_press_f9()
    except AttributeError:
        pass

def main():
    print('Macro tool running. Press F8 to start recording, F9 to play back.')
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()
if __name__ == '__main__':
    main()