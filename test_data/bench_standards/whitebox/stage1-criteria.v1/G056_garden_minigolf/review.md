# Benchmark standard review — G056_garden_minigolf

Directory: `/Users/yifanyang/Desktop/GameFactory-3A-game-bench/test_data/bench_standards/stage1/stage1-criteria.v1/G056_garden_minigolf`

Edit `<metric>.json` if needed, then approve with `python scripts_new/freeze_standards.py --stage 1 --approve G056_garden_minigolf`.

## gameness (28 checks)

Frozen source-only Gameness v4 outcome_frame_v1 standard for G056 (floating-garden mini golf), covering all 28 frozen CHECKS across the layout, guidance and event-feedback groups. Each check keeps its original criterion id, group and meaning and defines one principal visible outcome judged from native frames of the running build: recognisable white-box golf scene, complete and readable HUD, visible control and objective guidance, and the putt-event feedback chain (charge, strike, roll, barrier rebound, slope slowdown, out-of-bounds penalty with reset, hole-in celebration, stroke-cap banner, end-of-round lanterns into the summary). Timing, distances, ratios, coordinates and all branch/boundary behaviour remain source-level diagnostics carried verbatim in original_requirement_diagnostic_only and are not gates at the 50 or 100 tiers.

### `game.layout.hierarchy` 

- **Requirement**: 实际UI信息层级清楚，主要状态与次要信息可区分。
- **Visible goal**: In the in-game HUD the primary golf state — current hole, strokes used against the cap, and the charge value — reads as the visually dominant block, while the penalty count and camera-mode hint read as clearly subordinate secondary items.
- **Result frame (100%)**: One native gameplay frame carrying the HUD, in which the primary golf readouts stand out and the secondary readouts are visibly quieter.
- **Correct target**: The emphasised block must be the real hole / stroke / charge state of the running game, and the subordinate block must be the penalty count and the camera-mode indicator; neither may be swapped into the other's place.
- **Necessary context**: The gameplay frame alone is enough; hierarchy is judged from the HUD itself.
- **Basic function (50%)**: Playing a hole shows a HUD whose main golf state outranks its secondary readouts.
- **Basic bugs**: Every HUD item is drawn at the same weight and size, so primary and secondary information cannot be told apart.; HUD groups overlap or one group covers another, making the hierarchy unreadable.; The HUD shows debug or placeholder strings instead of the game's golf state.
- **Trigger modes**: automatic

### `game.layout.readable` 

- **Requirement**: 实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。
- **Visible goal**: Every visible HUD, menu and prompt text in the delivered frame is fully legible against its background, with no clipped labels, no overlapping strings and no text hidden behind scene geometry or effects.
- **Result frame (100%)**: A native gameplay or menu frame in which all golf-state labels and prompts are drawn whole and can be read in place.
- **Correct target**: The readable text must be the game's real golf-state strings and control labels, and each must sit where it stays readable over the 3D scene.
- **Necessary context**: One frame at normal play resolution is sufficient.
- **Basic function (50%)**: HUD and menu labels render complete with enough contrast to be read where they sit.
- **Basic bugs**: Labels are clipped or overflow their panel so words and digits are cut off.; Text is obscured by scene geometry, particles or another UI element.; Contrast or size is too poor to read the golf-state values.
- **Trigger modes**: automatic

### `game.guidance.controls` 

- **Requirement**: 实际游戏展示或清楚传达必要操作方法。
- **Visible goal**: A genuine game screen shows the player which inputs run the game — aiming, charging and releasing the putt, restarting the hole, switching camera mode and pausing — as an on-screen prompt or a clearly readable key legend.
- **Result frame (100%)**: A native title, HUD or pause frame carrying a visible control prompt or key legend for the putt controls.
- **Correct target**: The listed keys must be the ones this build actually binds for aim, charge/putt, restart, camera toggle and pause, and they must be presented inside the running game rather than in a document.
- **Necessary context**: One game screen suffices; a title, in-hole HUD or pause overlay all qualify.
- **Basic function (50%)**: The game itself tells the player the controls needed to play.
- **Basic bugs**: No control instructions appear on any in-game screen.; The displayed keys do not correspond to actions that work in this build.; Control guidance exists only outside the game, so the player never sees it while playing.
- **Trigger modes**: automatic, input

### `expanded.Q.s0001` 

- **Requirement**: 白模外观验收（允许几何体、纯色和标签；只验轮廓、相对比例、空间/色块关系与可读性，不要求最终材质、精细光照或成品模型）：- I07 输入延迟目标：蓄力/击球按键到画面反馈 ≤ 50 毫秒（手感关键） 仅评可视部分，声音不视为通过。
- **Visible goal**: The white-box course reads as golf — ball, tee, cup with flag, ground, slope and barriers distinguishable by outline, proportion and colour — and the charge or putt input immediately changes the picture.
- **Result frame (100%)**: A native gameplay frame of the white-box course taken at or immediately after the charge/putt input, showing ball, cup and flag, course geometry, and the visible response to the input.
- **Correct target**: The ball, cup and flag must be the game's actual objects in their true relative placement, and the visible reaction must be caused by the player's charge or putt action rather than by an idle or scripted animation.
- **Necessary context**: One gameplay frame captured as the input is applied; audio is not part of the pass.
- **Basic function (50%)**: Pressing to charge or putt visibly changes the course view at once, on a course whose golf elements are identifiable in white-box form.
- **Basic bugs**: Charge or putt input leaves the screen visually unchanged.; Ball, cup or flag cannot be identified on screen, so the scene does not read as a golf shot.; The visible reaction is not caused by the input: it plays before the press or without any player action.
- **Trigger modes**: input, held

### `expanded.G.s0005` 

- **Requirement**: - I06 UI 必须显示的状态：当前洞号、本洞已用杆数与上限、蓄力条数值、罚杆数、镜头模式提示
- **Visible goal**: During a hole the HUD shows the required readouts together: the current hole, strokes used against the per-hole cap, the charge value, the penalty count and the camera-mode indicator, each attached to the right quantity.
- **Result frame (100%)**: A native in-hole gameplay frame whose HUD carries the hole number, strokes-versus-cap, charge value, penalties and camera mode at the same time.
- **Correct target**: Each readout must name its own quantity: the hole being played, strokes kept separate from the cap, penalties separate from strokes, and the camera indicator showing the active view.
- **Necessary context**: One gameplay frame during a hole is enough.
- **Basic function (50%)**: Entering a hole displays the complete set of required golf-state readouts.
- **Basic bugs**: One or more of the required readouts is missing from the HUD.; Values are attached to the wrong quantity, e.g. penalties shown as strokes or the cap shown as strokes used.; The camera-mode indicator is absent, so the player cannot tell which view is active.
- **Trigger modes**: automatic

### `expanded.G.s0006` 

- **Requirement**: HUD 对照见 rubric。
- **Visible goal**: The gameplay HUD appears as one organised golf panel whose items match the game's own HUD definition — hole, strokes against cap, charge value, penalties, camera mode and state or warning labels — rather than as ad-hoc floating text.
- **Result frame (100%)**: A native gameplay frame showing the HUD as a coherent panel with its readouts grouped as defined.
- **Correct target**: The panel must belong to live gameplay and hold the defined golf fields in their intended grouping; developer overlays or debug strips are not the HUD.
- **Necessary context**: One gameplay frame is sufficient to compare the HUD with its definition.
- **Basic function (50%)**: Playing shows the specified HUD panel with its defined fields in place.
- **Basic bugs**: The defined HUD is missing and only scattered text or a debug overlay is shown.; HUD fields are thrown on screen with no grouping, so the panel cannot be read as the defined HUD.; HUD content is placeholder or editor text unrelated to the defined golf fields.
- **Trigger modes**: automatic

### `expanded.G.s0001` 

- **Requirement**: - S04 最低完整流程：标题、三洞球场、每洞 HUD（当前杆数）、总结算、重开必须全部存在且有真实入口。
- **Visible goal**: The title screen, per-hole play with its stroke HUD, and the final summary are all real, reachable screens of the build, with a start entry on the title and a restart entry on the summary.
- **Result frame (100%)**: Native frames of the title with a visible start control and of the summary showing the round result with a restart control, both reached inside the running build.
- **Correct target**: The start control must lead into the three-hole round, the per-hole HUD must show that hole's strokes, and the summary must present the played round's totals with a restart that returns to play.
- **Necessary context**: Because the flow spans title, holes and summary, those screens are the minimum; the course layout itself is a separate check.
- **Basic function (50%)**: The build offers a working start → play → summary → restart loop through real screens.
- **Basic bugs**: Title or summary exists only as a non-interactive mock with no working entry.; No restart path exists, so the round cannot be replayed.; The final screen shows no round result at all.
- **Trigger modes**: automatic, input, delayed

### `expanded.G.s0007` 

- **Requirement**: - L03 目标物/交互物/场景/UI 对象：本 spec §3–§9 引用的界面元素（标题/HUD/结算/暂停/视频播放层）与交互物逐类存在且运行时可进入
- **Visible goal**: Every referenced class exists in the running build — in the scene the ball, cup and flag, terrain, barriers, aim line and charge bar, and as overlays the title, HUD, summary, pause and video layer — each enterable during play.
- **Result frame (100%)**: Native frames from the running build showing the scene objects (ball, cup and flag, course geometry, aim and charge UI) and each UI layer actually opened.
- **Correct target**: Each class must be represented by the object or layer it names — an unrelated stand-in does not make the class present — and each UI layer must be enterable during play rather than merely drawn.
- **Necessary context**: Several screens are inherent because the check covers scene objects and UI layers; nothing beyond them is inferred.
- **Basic function (50%)**: The build contains and can open every referenced object and UI class.
- **Basic bugs**: An entire referenced class is missing, e.g. no hole cup or flag in the scene.; A referenced object is replaced by an unrelated stand-in, so that class is not really present.; A UI layer is drawn but cannot be entered during play.
- **Trigger modes**: automatic, input

### `expanded.G.s0008` 

- **Requirement**: 数量与属性以 L01/L02 与 G 系为准。
- **Visible goal**: The hole carries its declared objects in the declared counts: one ball, a cup with flag and a tee at the hole, the terrain and barrier set that hole is declared to have, plus the aim line, charge bar and trail.
- **Result frame (100%)**: A native overview frame of a hole in which ball, cup, flag, tee, terrain type and barriers can be counted and identified, with the aiming and charge UI present.
- **Correct target**: The count per class and the identity of each object must match the declared course — the right number of balls and cups, one flag and tee per cup, and the terrain and barrier configuration that hole is declared to have.
- **Necessary context**: An overview or wide frame per hole is the minimum for counting, and the camera overview mode provides it during play.
- **Basic function (50%)**: The generated course holds the declared objects in the declared counts and kinds.
- **Basic bugs**: A cup, flag or tee is missing at a hole.; Extra or duplicated objects appear, e.g. more than one ball in play.; A hole's declared terrain or barrier set is wrong, e.g. a flat hole built with a slope or a declared barrier absent.
- **Trigger modes**: automatic, input

### `expanded.G.s0013` 

- **Requirement**: 事件【蓄力开始】实际发生时可视表现为【蓄力条展开＋数值跳动】，结束条件【松开或取消】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: While the player holds to charge, the charge bar visibly opens out and its value updates, so a mid-charge state looks clearly different from the resting state.
- **Result frame (100%)**: Native frames of the resting HUD and of the same HUD during the hold, where the bar has expanded and its value has moved.
- **Correct target**: The element that grows must be the putt charge indicator tied to the hold, and its displayed value must track the fill; a decorative animation with no real charge value does not qualify.
- **Necessary context**: A before / during pair is needed because the outcome is a change over the hold; audio is not evaluated.
- **Basic function (50%)**: Holding the charge input opens the charge bar and drives its value.
- **Basic bugs**: The charge bar never appears or does not change while charging.; The bar fills but its value stays frozen, so charge strength cannot be read.; Some generic effect expands instead of the charge indicator, with no link to the charge.
- **Trigger modes**: held, input

### `expanded.G.s0014` 

- **Requirement**: 事件【击球】实际发生时可视表现为【球推出＋草地小尘环＋轨迹残影启动】，结束条件【残影 0.5s 渐隐】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: On release the ball is visibly pushed away from its spot and starts rolling, a small dust ring appears at the strike point on the ground, and the trajectory trail starts from the ball.
- **Result frame (100%)**: A native frame at or just after release showing the ball displaced from the contact point, a ground dust puff at that point, and the trail already beginning.
- **Correct target**: The displacement must be the putted ball itself, the dust must sit at the contact point where the ball was struck, and the trail must be attached to the ball's new path.
- **Necessary context**: The strike effect is transient, so a frame at the release moment plus one immediately after is the minimum to confirm it; audio is not evaluated.
- **Basic function (50%)**: Releasing the putt launches the ball with dust at the strike point and a trail starting along its path.
- **Basic bugs**: The ball does not move after release.; Trail or dust plays while the ball stays at rest.; Dust appears away from the strike point, unrelated to where the ball left.
- **Trigger modes**: input

### `expanded.G.s0015` 

- **Requirement**: 事件【球滚动】实际发生时可视表现为【轨迹残影跟随＋草浪压痕】，结束条件【球停】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: While the ball is rolling, a trail follows it along the travelled path and the grass shows a pressed, flattened mark behind it.
- **Result frame (100%)**: A native mid-roll frame with the ball in motion, the trail aligned behind it, and a flattened grass mark along the path already covered.
- **Correct target**: Both the trail and the grass mark must trace this ball's actual path and lie behind the ball; a fixed pre-drawn streak does not count.
- **Necessary context**: A mid-roll frame is required because the state exists only while rolling; a second frame along the path helps confirm the trail follows.
- **Basic function (50%)**: Rolling is visualised by a trail and a pressed grass mark that follow the ball.
- **Basic bugs**: The trail is detached from the ball or points away from its direction of travel.; No grass indentation appears while the ball rolls.; Trail or mark is drawn where the ball has not travelled.
- **Trigger modes**: automatic

### `expanded.G.s0016` 

- **Requirement**: 事件【碰撞挡板】实际发生时可视表现为【火花小粒子＋球体挤压回弹】，结束条件【回弹完成】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: When the ball meets a barrier, a burst of small sparks shows at the contact and the ball visibly compresses and rebounds off the barrier.
- **Result frame (100%)**: A native impact frame showing the ball at the barrier, sparks at the contact point, and a squashed ball carrying away from the wall.
- **Correct target**: The contact must be between the ball and the barrier geometry, the sparks must sit at that contact point, and the squash and rebound must be the ball's own reaction.
- **Necessary context**: The contact frame plus the next one are needed to show the rebound; audio is not evaluated.
- **Basic function (50%)**: Ball-to-barrier contact produces spark feedback and a squashed rebound.
- **Basic bugs**: The ball passes through the barrier without colliding.; Sparks play but the ball does not rebound off the barrier.; Sparks appear away from the meeting point of ball and wall.
- **Trigger modes**: automatic

### `expanded.G.s0017` 

- **Requirement**: 事件【上坡减速】实际发生时可视表现为【瞄准线透明度提示（击球前）/球速渐减】，结束条件【坡段结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: On a sloped hole the aiming line is visibly fainter over the slope before the shot, and after the putt the ball visibly slows while climbing that slope instead of rolling at a steady pace.
- **Result frame (100%)**: Native frames of the slope hole: an aiming frame where the line dims along the rising segment, and a rolling frame where the ball's progress slackens on the climb.
- **Correct target**: The faint stretch must be the aiming line over the actual upslope, readable as a slowdown warning, and later the ball must slow on that same rising ground.
- **Necessary context**: The pre-putt aim frame and the rolling frame both belong to the same information and are needed to show it; audio is not evaluated.
- **Basic function (50%)**: The slope is communicated as a slowdown — before the shot by the aim line, during the roll by the ball slowing.
- **Basic bugs**: The aiming line shows no slope indication over the uphill segment.; The ball does not slow at all on the climb.; The dimming or slowdown occurs on flat ground or the wrong segment of the course.
- **Trigger modes**: input, held, automatic

### `expanded.G.s0018` 

- **Requirement**: 事件【出界】实际发生时可视表现为【球坠云＋镜头拉高＋「界外＋1 杆」提示】，结束条件【复位完成】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: When the ball leaves the course boundary it visibly drops away over the cloud below, the view rises to a higher vantage, and an on-screen notice says the shot went out of bounds and a penalty stroke was added.
- **Result frame (100%)**: A native frame at the boundary event showing the ball beyond the course edge above the cloud, a raised camera, and the out-of-bounds penalty notice, with the ball back in play afterwards.
- **Correct target**: The falling object must be the ball beyond the course edge; the notice must state out-of-bounds together with the added penalty stroke, and play must resume from the previous position.
- **Necessary context**: The event frame plus the post-reset frame are the minimum, since the outcome includes recovery; audio is not evaluated.
- **Basic function (50%)**: Leaving the course triggers a visible out-of-bounds fall, a penalty notice and a reset back into play.
- **Basic bugs**: The ball vanishes with no out-of-bounds indication at all.; The notice reports the wrong outcome, such as success or a hole completion, or omits the penalty stroke.; After the event the ball is never returned to a playable position.
- **Trigger modes**: automatic, delayed

### `expanded.G.s0019` 

- **Requirement**: 事件【入洞】实际发生时可视表现为【球旋入洞杯＋旗杆亮灯＋花瓣迸溅】，结束条件【进入下一洞】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: When the ball reaches the cup it visibly sinks and spirals into the hole, the flag lights up and a petal burst plays, and the game then moves on to the next hole.
- **Result frame (100%)**: A native frame at the cup showing the ball at or entering the hole with the flag lit and petals bursting, followed by the next hole's opening frame.
- **Correct target**: The sink must happen at the cup the player putted toward, the flag light and petals belong to that cup, and the following state is the next hole rather than the same hole continuing.
- **Necessary context**: The cup frame plus one frame after the transition are needed to confirm the event ends in an advance.
- **Basic function (50%)**: A ball holed at the cup produces sink, flag light and petals, then play advances.
- **Basic bugs**: The ball reaches the cup but is not registered as holed, with no transition.; The celebration plays at a different cup or away from the hole.; The effect plays even though the ball missed the cup.
- **Trigger modes**: automatic

### `expanded.G.s0020` 

- **Requirement**: 事件【达杆数上限】实际发生时可视表现为【「本洞按 8 杆计」横幅】，结束条件【推进下一洞】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: When the per-hole stroke cap is reached, a banner announces that the hole is scored at the cap, and the game then advances to the next hole without a hard failure.
- **Result frame (100%)**: A native frame carrying the cap banner over the hole, followed by a frame of the next hole in play.
- **Correct target**: The banner must state that this hole counts at the cap and must belong to the hole that hit the cap; the next state must be the following hole rather than a failure or restart screen.
- **Necessary context**: The banner frame and the following frame are needed to show both the message and the advance; audio is not evaluated.
- **Basic function (50%)**: Hitting the stroke limit shows a cap notice and moves play onward.
- **Basic bugs**: No banner or notice appears when the cap is reached.; The notice states a different outcome, such as failure or restart, or names the wrong hole.; Play stalls on the capped hole instead of advancing.
- **Trigger modes**: delayed, automatic

### `expanded.G.s0021` 

- **Requirement**: 事件【三洞完成】实际发生时可视表现为【花灯升空粒子】，结束条件【进入总结算】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: After the last hole is completed, a celebration of rising lanterns plays over the course and leads into the round summary.
- **Result frame (100%)**: A native frame of lanterns rising after the final hole, followed by the summary screen.
- **Correct target**: The lantern celebration must belong to the end of the round after all holes are done, and it must hand off to the summary rather than dropping back into play.
- **Necessary context**: The celebration frame plus the summary frame are needed to show the handoff.
- **Basic function (50%)**: Completing the round triggers a rising-lantern celebration into the summary.
- **Basic bugs**: Nothing plays at the end of the round; play cuts straight to the summary.; The celebration fires mid-hole, before the round is finished.; The celebration plays but no summary follows.
- **Trigger modes**: delayed, automatic

### `expanded.G.s0026` 

- **Requirement**: - F07 VFX 信息性与遮挡约束：瞄准虚线与蓄力条承担击球信息
- **Visible goal**: The aiming line and the charge bar are the visible carriers of shot information — direction and reach from the line, power from the bar — and neither is covered by particles, decoration or other UI.
- **Result frame (100%)**: A native aiming frame in which the dashed aim line and the charge bar are both drawn clearly and unobstructed over the scene.
- **Correct target**: The aim line must start at the ball and point along the current aim, the charge bar must show the current power, and neither may be hidden or visually overrun by effects.
- **Necessary context**: One aiming frame is enough when both elements are visible in it.
- **Basic function (50%)**: Direction and power are readable from the aim line and charge bar without obstruction.
- **Basic bugs**: The aim line points somewhere unrelated to the aim direction.; The charge bar or aim line is covered by particles, decor or another UI element.; No aim line is shown while aiming, leaving the shot's direction unreadable.
- **Trigger modes**: input, held

### `expanded.G.s0027` 

- **Requirement**: 轨迹残影承担落点复盘信息
- **Visible goal**: The trail left by the ball lets the player review the shot: it traces the path actually travelled, ends where the ball came to rest, and remains readable after the ball stops.
- **Result frame (100%)**: A native frame at or after the ball's stop in which the trail runs back along the travelled path with its far end at the ball's resting position.
- **Correct target**: The trail must correspond to this shot's real path and its end must coincide with where the ball actually stopped, so the landing can be judged from it.
- **Necessary context**: The stop frame is essential; a mid-roll frame may be added to establish the path.
- **Basic function (50%)**: The trail shows the real path so the player can review where the ball ended.
- **Basic bugs**: The trail does not follow the ball's path.; The trail ends somewhere other than where the ball stopped.; The trail is replaced by a fixed or pre-drawn line unrelated to this shot.
- **Trigger modes**: automatic

### `expanded.G.s0011` 

- **Requirement**: - F03 输入与延迟：见 I07（击球手感为 S 档核心，≤50 毫秒）。
- **Visible goal**: Pressing to charge or releasing the putt produces its visible effect — the charge response or the ball launching — at the same instant, so the shot responds directly under the player's hand.
- **Result frame (100%)**: A native frame captured as the input is applied in which the response is already on screen: the bar reacting or the ball already leaving the spot.
- **Correct target**: The visible change must be driven by the player's press or release on the putt control; a scripted animation that plays regardless of input does not demonstrate the input path.
- **Necessary context**: Frames at the input instant and just after are the minimum, since the outcome is the immediacy of the response; the delay figure itself is not judged from frames.
- **Basic function (50%)**: Charge and putt input are answered on screen the moment they are applied.
- **Basic bugs**: The charge or putt press shows no visible change on the input frame.; Only sound responds while the picture stays unchanged.; A canned animation plays on a fixed schedule regardless of when the player acts.
- **Trigger modes**: input, held

### `expanded.G.s0002` 

- **Requirement**: - G05 瞄准与轨迹反馈（本包冻结值）：击球准备时显示瞄准虚线——长度＝按当前蓄力的预计纯滚动距离 × 60%，不显示反弹/坡面后路径，坡面段虚线透明度降低 40% 提示减速
- **Visible goal**: While aiming, a dashed line runs from the ball along the aim direction and lengthens or shortens with the current charge, appearing fainter where it crosses sloped ground.
- **Result frame (100%)**: Native aiming frames at different charge levels on a hole, showing the dashed line's length change and a visibly fainter stretch over the slope.
- **Correct target**: The line must originate at the ball, follow the current aim, scale with the charge, terminate at the predicted stopping point, and be dimmer on the slope than on the flat; exact proportions are not judged from frames.
- **Necessary context**: Two aiming frames are needed because the outcome is a relation between charge and line, and a flat-versus-slope comparison; the length ratio stays in source review.
- **Basic function (50%)**: The dashed aim line communicates predicted roll length and slope slowdown while aiming.
- **Basic bugs**: The dashed line's length does not respond to changes in charge.; The line continues past the predicted stop or draws bounce and post-slope continuation paths.; The slope stretch looks the same as the flat stretch, giving no slowdown hint.
- **Trigger modes**: input, held

### `expanded.G.s0003` 

- **Requirement**: 蓄力条 0–100% 数值与当前蓄力同步
- **Visible goal**: The charge bar shows both a filled level and a numeric value, and the number agrees with the fill while the player charges.
- **Result frame (100%)**: A native frame during a charge with the bar partly filled and the numeric readout showing the matching value.
- **Correct target**: The number and the fill must describe the same current charge and both must move during the hold; a fixed label beside a moving bar is not correct information.
- **Necessary context**: Two frames at different charge levels establish that the two readouts track each other.
- **Basic function (50%)**: The charge number and the bar fill stay in agreement as the player charges.
- **Basic bugs**: The numeric value never changes while the bar fills.; The number and the fill contradict each other at the same moment.; The displayed value belongs to another quantity, such as the stroke count.
- **Trigger modes**: held, input

### `expanded.G.s0004` 

- **Requirement**: 球滚动中显示轨迹残影（0.5 秒渐隐，仅保留最近一条）。
- **Visible goal**: While the ball rolls a trail follows it, the trail fades away after the ball stops, and only the most recent shot's trail is present at any time.
- **Result frame (100%)**: A native mid-roll frame with the trail behind the ball, plus a later frame after the stop where the trail has faded and no earlier trail remains.
- **Correct target**: The trail must belong to the current shot's path, and no leftover trail from a previous shot may still be drawn alongside it.
- **Necessary context**: Frames during the roll and after the stop are needed because the fade is a gradual effect; the fade duration itself is not judged from frames.
- **Basic function (50%)**: Each shot leaves one trail that disappears after the ball stops instead of accumulating.
- **Basic bugs**: No trail appears while the ball rolls.; The trail persists after the ball stops, or old trails pile up on the course.; A previous shot's trail is shown instead of the current one.
- **Trigger modes**: automatic, delayed

### `expanded.G.s0034` 

- **Requirement**: 冻结玩法中的资源/路线/时机选择有可理解的代价与收益提示。
- **Visible goal**: Before a putt the screen shows the trade-off: the current power and the hole's route or terrain cues, such as a faint aim stretch over a slope or visible barriers, so risk and payoff can be weighed.
- **Result frame (100%)**: A native aiming frame on a hole with slope or barrier where power information and the route or terrain cues are visible together before the putt.
- **Correct target**: The cues must describe this hole's actual terrain and barriers and the actual current power; generic tooltip text unrelated to the layout does not convey the choice.
- **Necessary context**: One aiming frame on a hole with slope or barrier suffices when both power and route cues are on screen.
- **Basic function (50%)**: Shot choices come with visible information about their likely cost and payoff.
- **Basic bugs**: No cue at all about slope or barriers while aiming.; Cues contradict the terrain, e.g. a slowdown hint on flat ground.; No power information is visible, so the player cannot judge how far the ball will travel.
- **Trigger modes**: input, held

### `expanded.G.s0032` 

- **Requirement**: 核心操作产生的成功、失败或拒绝反馈可被区分；此处不重复计算 C2 数值正确性。
- **Visible goal**: The core putt's outcomes read differently on screen: a holed ball shows its cup celebration, a ball leaving the course shows a penalty notice and reset, and a refused shot changes neither the ball nor the stroke count.
- **Result frame (100%)**: Native frames of the three outcomes — cup celebration, out-of-bounds notice, and a refused attempt where nothing launches and the stroke count is unchanged.
- **Correct target**: Each feedback must be attached to the event it describes, so a penalty cannot be mistaken for a holed putt and a refusal cannot consume a stroke or launch the ball.
- **Necessary context**: Representative frames per outcome are needed because the check is about telling them apart.
- **Basic function (50%)**: Success, penalty and refusal each give a distinct, correct on-screen response.
- **Basic bugs**: All outcomes produce the same generic effect, so they cannot be told apart.; A refused shot still launches the ball or increments the stroke count.; An out-of-bounds event is presented as a success or a hole completion.
- **Trigger modes**: input, automatic, rejection

### `expanded.G.s0033` 

- **Requirement**: 目标进度、阶段变化与终局结果向玩家明确呈现。
- **Visible goal**: The screen keeps the round's progress legible — the HUD shows which hole of the round is being played — and at the end the summary presents the round's result, including the total against par and the penalties.
- **Result frame (100%)**: A native in-hole HUD frame showing the current hole within the round, plus the summary screen presenting the round's totals, comparison to par and penalties with a way onward.
- **Correct target**: The progress indicator must match the hole actually being played, and the summary numbers must be this round's real result rather than fixed or placeholder values.
- **Necessary context**: A hole frame and the summary frame are the minimum; the two stages cannot be shown in one screen.
- **Basic function (50%)**: Stage progress and the final round result are displayed from real game state.
- **Basic bugs**: The HUD gives no indication of which hole is being played.; The summary omits the comparison against par or the penalties.; The summary shows fixed numbers regardless of how the round was played.
- **Trigger modes**: automatic, delayed

### `expanded.G.s0031` 

- **Requirement**: 玩家能在操作前知道当前目标及可执行的下一步，不依赖阅读工程文档。
- **Visible goal**: Before acting, the player can learn the current aim of play and the next action from the game screen itself — an objective line naming the round's goal and a prompt or readable hint for the next putt step.
- **Result frame (100%)**: A native title or first in-hole frame carrying a visible objective line and a next-action prompt tied to aiming and charging a putt.
- **Correct target**: The objective must be this game's real goal — completing the round's holes within the stroke allowance — and the next action must match a control that actually works here.
- **Necessary context**: One screen suffices when goal and next action appear together.
- **Basic function (50%)**: The game states its current goal and the immediate next step on screen.
- **Basic bugs**: No objective or next-step text appears anywhere in the game.; The guidance describes a different game or objective than this round.; The hint names an action that does nothing in this build.
- **Trigger modes**: automatic, input

## mechanic (8 checks)

Source-only outcome standard for the three-hole floating-garden mini-golf putt mechanic (G056). Eight CHECKs each target one principal visible outcome of the putt loop: charge-and-release produces a rolling/rebounding ball, invalid strike attempts are rejected without spending a stroke, terrain (slope and bumper) alters the ball path, an unobstructed roll settles under friction alone, an out-of-bounds ball is restored to its last played position with one penalty stroke shown in the HUD, a sunk ball completes the hole and advances (to the next hole, or to the settlement panel after the last), a fast pass over the cup is not accepted as sunk, and the aiming line plus power readout track the charge while the shot leaves a trail. All fields describe only what a frame can show (which object, what visibly happens, which HUD/panel is on screen). Frozen numbers from G01-G05 (12 m/s at full charge, 1.5 m/s² flat friction, 3.0 m/s² along-slope, 0.6 restitution, 60% aim-line factor, 40% slope transparency drop, 0.5 s trail fade, 8-stroke cap, threshold speeds, camera degrees) are treated as diagnostic-only source evidence and are not restated as acceptance conditions.

### `atom.G056_garden_minigolf.WB.TC2.01.C2.tiered.01` 

- **Requirement**: 按 G02 公式生成初速向量 → 球滚动/反弹
- **Visible goal**: The player charges a putt in the striking view and releases it, and the golf ball visibly leaves its resting spot and travels across the course in the aimed direction instead of standing still or jumping at random.
- **Result frame (100%)**: A sequence of real gameplay frames showing the ball at rest on the fairway with the aim line and power bar, then the ball displaced well away from that spot, moving along the aimed direction, with the stroke counter advanced by one.
- **Correct target**: The single golf ball on the course surface, moving away from its resting position along the direction the player was aiming when the shot was released.
- **Necessary context**: The ball at rest, the aim direction and charged power must be visible before release, and the next frames must show that same ball moving on the course, tying the travel to the release.
- **Basic function (50%)**: Charging the power bar and releasing the button launches the ball so it rolls forward across the green in the aimed direction and gradually slows down.
- **Basic bugs**: Releasing the charged shot leaves the ball motionless at its resting spot, so no stroke visibly happens.; The ball launches but travels opposite to or far off the displayed aim direction.; The ball passes through the bumper or slope geometry without any rebound or deflection along its route.
- **Trigger modes**: input, automatic

### `atom.G056_garden_minigolf.WB.TC2.02.C2.tiered.02` 

- **Requirement**: 滚动中击球、全览模式击球 → 拒绝且不耗杆
- **Visible goal**: An attempt to strike the ball while it is still rolling, or while the overview camera mode is active, is refused: no new shot is launched and the displayed stroke count does not increase.
- **Result frame (100%)**: Frames of a strike attempt made under the refused condition, with the HUD stroke counter still showing its earlier value and the ball continuing on its existing path rather than being re-launched.
- **Correct target**: The golf ball together with the on-screen stroke counter in the HUD, both of which must remain unchanged by the refused attempt.
- **Necessary context**: The refusing condition must be visible — the ball in motion, or the whole-hole overview camera — and the stroke counter must be readable before and after the attempt to see no stroke was charged.
- **Basic function (50%)**: Pressing and releasing the shot control while the ball is rolling or while the overview camera is on produces no launch and no stroke deduction, leaving the ball and the stroke count as they were.
- **Basic bugs**: The refused attempt launches a fresh shot and the stroke counter increases.; The rolling ball visibly changes direction or restarts mid-roll in response to the attempt.; A shot is actually launched while the whole-hole overview camera is active.
- **Trigger modes**: rejection

### `atom.G056_garden_minigolf.WB.TC2.03.C2.tiered.03` 

- **Requirement**: 坡面改变速度分量（沿坡 3.0 米/秒²）；碰撞按恢复系数 0.6 反弹
- **Visible goal**: The ball's path is visibly altered by the course terrain: crossing a sloped section bends and speeds or slows its travel along the slope, and striking a wooden bumper sends it back off the bumper instead of continuing straight.
- **Result frame (100%)**: Gameplay frames where the moving ball reaches the sloped ground and visibly curves along it, then reaches the wooden bumper and moves back off its face, with the ball past the contact in the later frame.
- **Correct target**: The moving golf ball where it meets the sloped ground and the wooden bumper in the later holes, deflecting along the slope and rebounding away from the bumper's face.
- **Necessary context**: The slope or bumper must be visible in frame together with the approaching ball so the deflection can be attributed to the terrain, and the post-contact frames must show the ball on the course rather than off it.
- **Basic function (50%)**: A ball rolling into a slope or a bumper is deflected — it bends along the incline and bounces back off the wall with reduced speed — instead of treating the obstacle as flat, empty ground.
- **Basic bugs**: The ball passes through or clips inside the bumper and emerges on the far side without rebounding.; The ball keeps a straight, unchanged path across the sloped section as if the ground were flat.; On contact the ball is redirected along or into the obstacle rather than away from its face, or is stopped dead and left embedded in it.
- **Trigger modes**: input, automatic

### `atom.G056_garden_minigolf.WB.TC2.04.C2.tiered.04` 

- **Requirement**: 无碰撞则纯摩擦结算
- **Visible goal**: A ball struck across open flat fairway with no bumper or slope in its path slows down and visibly comes to rest on the green by itself, without being deflected or teleported.
- **Result frame (100%)**: Consecutive gameplay frames on a clear stretch of fairway showing the ball partway along its roll, then the same ball sitting still at a stopping point with the camera settled on it, the hole still unfinished.
- **Correct target**: The moving golf ball on unobstructed flat fairway, ending at rest some distance from where it was struck.
- **Necessary context**: The struck line of travel must be visible and free of bumper or slope contact, and the stopping frame must show the same ball stationary on the course so the stop can be read as friction rather than a cut or a reset.
- **Basic function (50%)**: After an unobstructed putt the ball decelerates smoothly and settles at rest on the green, ready for the next shot.
- **Basic bugs**: The ball keeps rolling indefinitely and never comes to rest.; The ball visibly bends or reverses on empty fairway as if it hit an invisible obstacle.; The ball rolls on a clear straight shot but sinks below the ground or off the visible course surface instead of stopping on it.
- **Trigger modes**: input, automatic

### `atom.G056_garden_minigolf.WB.TC2.05.C2.tiered.05` 

- **Requirement**: 回上一杆位＋罚 1 杆；连续界外不叠加惩罚上限以外的额外状态；镜头回上一杆位
- **Visible goal**: When the ball leaves the course and drops into the cloud sea, it is put back at the spot it was last struck from and the HUD shows one additional penalty stroke.
- **Result frame (100%)**: Frames of the ball falling past the course edge into the cloud, followed by the ball standing still again at its previous play position, with the HUD stroke or penalty count visibly one higher than before the fall.
- **Correct target**: The golf ball restored to the position of its previous stroke on the course, together with the HUD stroke and penalty figures that have increased by one.
- **Necessary context**: The departure over the course boundary must be visible together with the HUD count before the fall, and the restored ball must be shown at rest on the course with the updated HUD so the penalty and the return position can both be read.
- **Basic function (50%)**: A ball that goes out of bounds is respawned at the position of the last stroke and the player is charged a single penalty stroke, with the camera returning to that spot.
- **Basic bugs**: The ball is left outside the course or stays falling, never returning to a playable position.; The ball returns to the course but the HUD stroke or penalty count stays the same, so no penalty is charged.; The ball reappears somewhere other than the position of its last stroke, such as the tee of the current or next hole.
- **Trigger modes**: automatic, delayed

### `atom.G056_garden_minigolf.WB.TC2.06.C2.tiered.06` 

- **Requirement**: 本洞完成 → 下一洞；达 8 杆上限强制完成；三洞完成 → 总结算
- **Visible goal**: A ball resting in the cup completes the hole and play moves on: the view advances to a new hole, or, after the final hole, a settlement panel appears instead of play staying on the finished hole.
- **Result frame (100%)**: Frames of the ball settling into the cup beside the flag, then either the next hole's tee with the HUD hole number advanced, or, when this was the final hole, a summary panel of stroke totals against par.
- **Correct target**: The ball and cup of the just-finished hole, then the HUD hole indicator or the settlement panel that evidences hole completion and progression.
- **Necessary context**: The completed hole's cup and the ball inside it must be visible in the frames leading in, so the progression can be tied to a real sink rather than to an unrelated transition or a pause-menu reset.
- **Basic function (50%)**: Sinking the ball in the cup finishes the current hole and advances the game to the next hole, ending with the summary settlement once the last hole is done.
- **Basic bugs**: The ball rests in the cup with no hole-complete reaction, leaving play stuck on the same hole.; The hole advances but the HUD still shows the finished hole's number and stroke count instead of the new hole.; After the final hole the game returns to an earlier hole or the title screen with no settlement panel shown.
- **Trigger modes**: automatic, input

### `atom.G056_garden_minigolf.WB.TC2.07.C2.tiered.07` 

- **Requirement**: 高速掠过洞杯不判入洞（速度阈值）
- **Visible goal**: A ball struck hard enough to speed across the cup does not drop: it carries on past the hole and the hole is not counted as completed.
- **Result frame (100%)**: Frames showing the fast ball reaching and crossing the cup mouth, then continuing beyond the cup and coming to rest past it, with the HUD still on the same hole and no next-hole or settlement transition under way.
- **Correct target**: The fast-moving golf ball and the cup it passes over, with the ball ending up beyond the cup and the hole still open rather than registered as sunk.
- **Necessary context**: Both the cup and the fast ball must be visible as the ball crosses the cup opening, and the following frame must show the ball alive on the course beyond the cup so the pass can be distinguished from the ball stopping in it.
- **Basic function (50%)**: A ball crossing the cup opening at high speed is rejected by the hole and keeps rolling, so the hole stays in progress.
- **Basic bugs**: The fast pass is registered as a hole-in, advancing the hole or opening the settlement panel.; The ball is visibly captured or snapped into the cup mouth and stopped there despite its speed.; The shot is discarded — the ball resets or the stroke is refunded — instead of the ball being allowed to continue past the cup.
- **Trigger modes**: rejection, automatic

### `atom.G056_garden_minigolf.WB.TC2.08.C2.tiered.08` 

- **Requirement**: 瞄准虚线长度与坡面透明度按 G05 更新；蓄力条数值同步；击球后生成轨迹残影（0.5 秒渐隐，替换旧残影）
- **Visible goal**: While the player holds and varies the charge, the dashed aiming line and the on-screen power value visibly track the charge level, and once the shot is released the ball leaves a fading trail along the path it travels.
- **Result frame (100%)**: Frames taken during the charge showing the dashed aim line and the numeric power readout at different charge levels, followed by frames of the launched ball trailing a visible streak of its path that thin out behind it.
- **Correct target**: The aiming dashed line and the power-bar readout in the shot-preparation view, then the ball's own trail once the shot is released.
- **Necessary context**: The shot-preparation state with aim line and power value on screen must be shown while the charge changes, and the launched ball must be visible after release so the trail ties to its path.
- **Basic function (50%)**: The aim line and the power number respond to the player's hold — the line extends and the figure climbs with the charge — and the released ball leaves a trail that fades behind it.
- **Basic bugs**: The aim line stays a fixed length while the charge is held and changed.; The displayed power value does not move with the charge, or moves opposite to the aim line.; No trail appears behind the ball after the shot is released.
- **Trigger modes**: input, held

