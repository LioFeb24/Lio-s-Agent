from pynput import keyboard, mouse
import json
import time

def record_macro(output_file='macro.json', stop_key=keyboard.Key.esc):
    events = []
    start_time = time.time()

    def on_press(key):
        events.append({'type': 'key_press', 'key': str(key), 'time': time.time() - start_time})
        if key == stop_key:
            return False

    def on_release(key):
        events.append({'type': 'key_release', 'key': str(key), 'time': time.time() - start_time})

    def on_click(x, y, button, pressed):
        events.append({'type': 'mouse_click', 'x': x, 'y': y, 'button': str(button), 'pressed': pressed, 'time': time.time() - start_time})

    def on_move(x, y):
        events.append({'type': 'mouse_move', 'x': x, 'y': y, 'time': time.time() - start_time})
    k_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    m_listener = mouse.Listener(on_click=on_click, on_move=on_move)
    k_listener.start()
    m_listener.start()
    k_listener.join()
    m_listener.stop()
    with open(output_file, 'w') as f:
        json.dump(events, f, indent=2)
    print(f'Macro saved to {output_file}')
if __name__ == '__main__':
    record_macro()