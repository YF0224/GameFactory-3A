# Benchmark standard review — DEMO_snake_godot

Directory: `/Users/yifanyang/Desktop/GameFactory-3A-game-bench/test_data/bench_standards/whitebox/stage1-criteria.v1/DEMO_snake_godot`

Edit `<metric>.json` if needed, then approve with `python scripts_new/freeze_standards.py --stage x --approve DEMO_snake_godot`.

## gameness (4 checks)

Synthetic Snake example draft. Human approval is still required.

### `game.layout.hierarchy` layout

- **Requirement**: 实际UI信息层级清楚，主要状态与次要信息可区分。
- **Visible goal**: 实际UI信息层级清楚，主要状态与次要信息可区分。
- **Result frame (100%)**: 实际UI信息层级清楚，主要状态与次要信息可区分。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 实际UI信息层级清楚，主要状态与次要信息可区分。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `game.layout.readable` layout

- **Requirement**: 实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。
- **Visible goal**: 实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。
- **Result frame (100%)**: 实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `game.guidance.controls` guidance

- **Requirement**: 实际游戏展示或清楚传达必要操作方法。
- **Visible goal**: 实际游戏展示或清楚传达必要操作方法。
- **Result frame (100%)**: 实际游戏展示或清楚传达必要操作方法。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 实际游戏展示或清楚传达必要操作方法。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `expanded.end` feedback

- **Requirement**: 终局提供清楚的成功、失败或拒绝反馈。
- **Visible goal**: 终局提供清楚的成功、失败或拒绝反馈。
- **Result frame (100%)**: 终局提供清楚的成功、失败或拒绝反馈。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 终局提供清楚的成功、失败或拒绝反馈。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

## mechanic (8 checks)

Synthetic Snake example draft. Human approval is still required.

### `atom.move.move` move

- **Requirement**: 方向键或 WASD 可以改变蛇前进的方向。
- **Visible goal**: 蛇在棋盘上沿玩家选择的方向移动。
- **Result frame (100%)**: 蛇在棋盘上沿玩家选择的方向移动。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 蛇在棋盘上沿玩家选择的方向移动。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `atom.food.food` food

- **Requirement**: 蛇碰到食物后会吃掉食物。
- **Visible goal**: 蛇已经到达食物所在的位置并吃掉食物。
- **Result frame (100%)**: 蛇已经到达食物所在的位置并吃掉食物。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 蛇已经到达食物所在的位置并吃掉食物。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `atom.grow.grow` grow

- **Requirement**: 吃到食物后蛇身增长。
- **Visible goal**: 蛇吃到食物后出现增长的蛇身。
- **Result frame (100%)**: 蛇吃到食物后出现增长的蛇身。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 蛇吃到食物后出现增长的蛇身。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `atom.wall.wall` wall

- **Requirement**: 撞到棋盘边界后游戏失败。
- **Visible goal**: 蛇碰到棋盘边界后画面显示失败状态。
- **Result frame (100%)**: 蛇碰到棋盘边界后画面显示失败状态。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 蛇碰到棋盘边界后画面显示失败状态。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `atom.self.self` self

- **Requirement**: 撞到自己的蛇身后游戏失败。
- **Visible goal**: 蛇碰到自身后画面显示失败状态。
- **Result frame (100%)**: 蛇碰到自身后画面显示失败状态。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 蛇碰到自身后画面显示失败状态。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `atom.win.win` win

- **Requirement**: 吃到三个食物后游戏胜利。
- **Visible goal**: 完成食物目标后画面显示胜利状态。
- **Result frame (100%)**: 完成食物目标后画面显示胜利状态。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 完成食物目标后画面显示胜利状态。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `atom.restart.restart` restart

- **Requirement**: 按 R 可以从终局重新开始游戏。
- **Visible goal**: 重新开始后棋盘上出现可继续游玩的初始蛇和食物。
- **Result frame (100%)**: 重新开始后棋盘上出现可继续游玩的初始蛇和食物。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 重新开始后棋盘上出现可继续游玩的初始蛇和食物。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

### `atom.pause.pause` pause

- **Requirement**: 空格可以暂停和继续游戏。
- **Visible goal**: 游戏画面能够显示暂停状态。
- **Result frame (100%)**: 游戏画面能够显示暂停状态。
- **Correct target**: 贪吃蛇游戏中的蛇、食物或相应状态信息。
- **Necessary context**: 游戏棋盘和相关状态信息可见。
- **Basic function (50%)**: 游戏画面能够显示暂停状态。
- **Basic bugs**: 对应功能没有可见响应。; 可见结果作用于错误的对象。
- **Trigger modes**: input, automatic

