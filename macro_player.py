from pynput import keyboard, mouse
import json
import time

def play_macro(input_file='macro.json', speed=1.0):
    with open(input_file, 'r') as f:
        events = json.load(f)
    k_controller = keyboard.Controller()
    m_controller = mouse.Controller()
    start_time = time.time()
    last_event_time = 0
    for event in events:
        event_time = event['time'] / speed
        wait = event_time - last_event_time
        if wait > 0:
            time.sleep(wait)
        last_event_time = event_time
        if event['type'] == 'key_press':
            try:
                key = keyboard.Key[event['key'].split('.')[1]] if 'Key.' in event['key'] else event['key'].strip("'")
                k_controller.press(key)
            except:
                k_controller.press(event['key'])
        elif event['type'] == 'key_release':
            try:
                key = keyboard.Key[event['key'].split('.')[1]] if 'Key.' in event['key'] else event['key'].strip("'")
                k_controller.release(key)
            except:
                k_controller.release(event['key'])
        elif event['type'] == 'mouse_click':
            m_controller.position = (event['x'], event['y'])
            btn = mouse.Button.left if 'left' in event['button'] else mouse.Button.right
            if event['pressed']:
                m_controller.press(btn)
            else:
                m_controller.release(btn)
        elif event['type'] == 'mouse_move':
            m_controller.position = (event['x'], event['y'])
    print('Playback finished.')
if __name__ == '__main__':
    play_macro()