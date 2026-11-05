# SAMPLEY

Карманный **сэмплер на Raspberry Pi Zero W / Zero 2 W**: 16 пэдов с RGB-подсветкой,
4 энкодера, цветной экран 2″, микрофон, динамики, наушники, линейный вход.
Нажал пэд — играет звук; можно записывать свои звуки, собирать бит в
секвенсоре, сохранять наборы. Аккумулятор внутри, зарядка по USB-C, работает
во время зарядки — «встроенный UPS», как UPS-Lite, только на своей плате.

Сделан по образцу [KODY](https://github.com/kl1ms1/KODY): Pi вставляется в
плату «бутербродом», кнопками и питанием занимается свой микроконтроллер,
софт на Python с симуляцией на компьютере.

| Игра | Шаги | Запись |
|---|---|---|
| ![](docs/img/screen_play.png) | ![](docs/img/screen_step.png) | ![](docs/img/screen_sample.png) |

Послушать встроенные звуки и демо-бит: [`docs/demo.wav`](docs/demo.wav) — всё синтезировано кодом.

## Документы

- [`docs/concept.md`](docs/concept.md) — как выглядит, управление, электроника, питание, реализуемость
- [`docs/breadboard.md`](docs/breadboard.md) — **этап 1:** макетка из готовых модулей, распиновка, установка
- [`docs/shopping-list.md`](docs/shopping-list.md) — что купить
- [`docs/roadmap.md`](docs/roadmap.md) — план

## Коротко о железе

| Блок | Чем |
|---|---|
| Мозги | Raspberry Pi Zero 2 W (или Zero W — меньше голосов, больше задержка) |
| Звук | Кодек WM8960: наушники, 2 динамика по 1 Вт, микрофон, линейный вход |
| Экран | 2.0″ IPS 320×240, ST7789, SPI |
| Пэды, кнопки, энкодеры, подсветка | Микроконтроллер RP2040 ↔ Pi по UART |
| Питание | USB-C → BQ25895 (зарядка + работа при зарядке) → TPS61088 (5 В), защита DW01A, проценты MAX17048, ползунок с безопасным выключением |

## Софт

```
software/
  sampley/
    engine.py      звуковой движок: голоса, тон, режимы, группы глушения
    sequencer.py   16 шагов × 8 паттернов, свинг, запись вживую
    recorder.py    запись с микрофона / линии с автостартом
    kit.py         наборы на карте памяти (WAV + kit.json)
    kit_synth.py   встроенные звуки, синтезированные кодом
    app.py         что делают пэды, кнопки и энкодеры на каждом экране
    ui.py          экран 320×240
    controls.py    протокол с микроконтроллером
    hw.py          экран ST7789, UART, датчик заряда, звук
    board.py       Zero W / Zero 2 W — выбирается само
    pins.py        карта GPIO
  tests/           python3 -m unittest
  install.sh       установка на Pi + автозапуск
firmware/pico/main.py   прошивка микроконтроллера (MicroPython)
tools/gen_shopping_list.py
```

Запуск:

```bash
cd software
python3 -m unittest discover -s tests -t .   # тесты
python3 -m sampley --demo ../out             # демо-бит в WAV + картинки экранов, без железа
python3 -m sampley --sim                     # на компьютере: окно + клавиатура (pip install pygame sounddevice)
python3 -m sampley                           # на Pi
```

В симуляции: пэды — `1234 / qwer / asdf / zxcv`, энкодеры — `5 6`, `t y`,
`g h`, `b n` (нажатие `7 u j m`), Shift — SHIFT, Пробел — PLAY, Enter — REC.
