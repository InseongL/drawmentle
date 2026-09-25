# 속성 사전 검토 보고서

- 전체: 345개 / 생성: 12개 / 미생성: 333개
- 자동 검사는 형식·태그·누락 검증입니다. 사실성이나 게임의 재미를 검증한 것이 아닙니다.
- 표시된 문제가 없어도 생성 초안은 미검수 상태입니다.

| 대상 | 상태 | 우선 검토 이유 |
|---|---|---|
| fan | unreviewed | classification:uncertain, shape:uncertain, catalog_requires_review, author_notes |
| bird | unreviewed | function:uncertain, catalog_requires_review, author_notes |
| cup | unreviewed | catalog_requires_review, author_notes |
| mug | unreviewed | catalog_requires_review, author_notes |
| airplane | unreviewed | author_notes |
| apple | unreviewed | author_notes |
| banana | unreviewed | author_notes |
| car | unreviewed | author_notes |
| bicycle | unreviewed | 일반 표본 검토 |
| giraffe | unreviewed | 일반 표본 검토 |
| helicopter | unreviewed | 일반 표본 검토 |
| horse | unreviewed | 일반 표본 검토 |

## 항목별 초안

### fan (선풍기)

- **classification** [uncertain]: (태그 보류)
  - 설명: 부채와 전기 선풍기 중 어떤 의미를 채택할지 표본 확인이 필요함
- **shape** [uncertain]: (태그 보류)
  - 설명: 부채꼴 구조와 회전 날개 구조가 모두 가능해 단정하지 않음
- **function** [known]: cooling
  - 설명: 공기를 움직여 더위를 식히는 데 사용됨
- 검토 메모: 표본을 확인하기 전에는 분류와 형태 벡터를 생성하지 않는다.

### bird (새)

- **classification** [known]: animal, bird
  - 설명: 부리와 깃털을 가진 조류의 넓은 범주
- **shape** [known]: wings, beak, two_legs
  - 설명: 몸통에 날개 한 쌍과 부리, 두 다리가 있는 형태
- **function** [uncertain]: (태그 보류)
  - 설명: 비행이 대표적이지만 모든 조류가 날지는 않아 범주의 대표 행동 정책이 필요함
- 검토 메모: 개별 조류 클래스와 겹치는 넓은 범주다.

### cup (컵)

- **classification** [known]: container
  - 설명: 음료를 담아 마시는 용기
- **shape** [known]: cylindrical, opening, hollow
  - 설명: 위가 열려 있고 내부에 액체를 담을 수 있는 원통에 가까운 형태
- **function** [known]: holding_liquid
  - 설명: 마실 액체를 담음
- 검토 메모: 머그와 커피 컵 클래스의 시각적 경계를 실제 표본으로 확인해야 한다.

### mug (머그잔)

- **classification** [known]: container
  - 설명: 음료를 담아 마시는 손잡이 있는 용기
- **shape** [known]: cylindrical, opening, hollow, handle
  - 설명: 위가 열린 몸체의 옆면에 손잡이가 붙음
- **function** [known]: holding_liquid
  - 설명: 마실 액체를 담음
- 검토 메모: 컵과 커피 컵 클래스와의 경계를 확인해야 한다.

### airplane (비행기)

- **classification** [known]: vehicle, aircraft
  - 설명: 사람이나 화물을 공중으로 운송하는 항공 탈것
- **shape** [known]: elongated, wings, windows
  - 설명: 길쭉한 동체 양옆으로 날개가 뻗고 창문이 줄지어 있는 형태
- **function** [known]: flying, transport_people, transport_goods
  - 설명: 하늘을 날아 사람과 물건을 운송함
- 검토 메모: 대표적인 여객기 형태를 가정한 예시 초안이며 실제 그림 표본 검수 전이다.

### apple (사과)

- **classification** [known]: food, fruit
  - 설명: 먹을 수 있는 과일
- **shape** [known]: round, stem
  - 설명: 대체로 둥근 윤곽에 짧은 꼭지가 붙음
- **function** [known]: eating
  - 설명: 식품으로 먹음
- 검토 메모: 대표 색상은 품종에 따라 달라진다. 현재 색상 모듈은 비활성이다.

### banana (바나나)

- **classification** [known]: food, fruit
  - 설명: 먹을 수 있는 과일
- **shape** [known]: elongated, stem
  - 설명: 길쭉하게 휘어진 몸체와 끝부분의 꼭지가 있음
- **function** [known]: eating
  - 설명: 식품으로 먹음
- 검토 메모: 곡선 형태의 세분화 태그가 필요하면 어휘 사전의 다음 버전에서 추가할 수 있다.

### car (자동차)

- **classification** [known]: vehicle, land_vehicle
  - 설명: 도로 위에서 사람을 운송하는 육상 탈것
- **shape** [known]: elongated, four_wheels, windows
  - 설명: 차체에 네 바퀴와 창문이 달린 구조
- **function** [known]: transport_people
  - 설명: 도로를 따라 사람을 운송함
- 검토 메모: 등록 속성은 물체 기준이다. 옆모습 그림에서는 바퀴 두 개만 보일 수 있다.

### bicycle (자전거)

- **classification** [known]: vehicle, land_vehicle
  - 설명: 사람이 페달을 밟아 이동하는 육상 탈것
- **shape** [known]: two_wheels, handle
  - 설명: 두 바퀴를 연결하는 프레임과 조향 손잡이가 있음
- **function** [known]: transport_people, exercise
  - 설명: 사람의 이동과 운동에 사용됨

### giraffe (기린)

- **classification** [known]: animal, mammal
  - 설명: 육상에서 생활하는 초식 포유류
- **shape** [known]: four_legs, long_neck, spots, horns
  - 설명: 매우 긴 목과 네 다리, 반점 무늬와 머리 위의 작은 뿔 모양 돌기가 있음
- **function** [known]: walking, grazing
  - 설명: 걸어 다니며 높은 곳의 나뭇잎 등을 먹음

### helicopter (헬리콥터)

- **classification** [known]: vehicle, aircraft
  - 설명: 회전 날개로 비행하는 항공 탈것
- **shape** [known]: elongated, rotor, windows
  - 설명: 동체 위에 회전 날개가 있고 뒤로 긴 꼬리 부분이 뻗음
- **function** [known]: flying, transport_people, rescue
  - 설명: 비행하며 사람을 운송하거나 구조에 활용됨

### horse (말)

- **classification** [known]: animal, mammal
  - 설명: 육상에서 생활하는 초식 포유류
- **shape** [known]: four_legs, long_tail, elongated
  - 설명: 길쭉한 몸통과 네 다리, 긴 꼬리를 가진 형태
- **function** [known]: walking, running, grazing
  - 설명: 걷거나 달리며 풀을 먹음


## 미생성 카테고리

aircraft_carrier, alarm_clock, ambulance, angel, animal_migration, ant, anvil, arm, asparagus, axe, backpack, bandage, barn, baseball, baseball_bat, basket, basketball, bat, bathtub, beach, bear, beard, bed, bee, belt, bench, binoculars, birthday_cake, blackberry, blueberry, book, boomerang, bottlecap, bowtie, bracelet, brain, bread, bridge, broccoli, broom, bucket, bulldozer, bus, bush, butterfly, cactus, cake, calculator, calendar, camel, camera, camouflage, campfire, candle, cannon, canoe, carrot, castle, cat, ceiling_fan, cello, cell_phone, chair, chandelier, church, circle, clarinet, clock, cloud, coffee_cup, compass, computer, cookie, cooler, couch, cow, crab, crayon, crocodile, crown, cruise_ship, diamond, dishwasher, diving_board, dog, dolphin, donut, door, dragon, dresser, drill, drums, duck, dumbbell, ear, elbow, elephant, envelope, eraser, eye, eyeglasses, face, feather, fence, finger, fire_hydrant, fireplace, firetruck, fish, flamingo, flashlight, flip_flops, floor_lamp, flower, flying_saucer, foot, fork, frog, frying_pan, garden, garden_hose, goatee, golf_club, grapes, grass, guitar, hamburger, hammer, hand, harp, hat, headphones, hedgehog, helmet, hexagon, hockey_puck, hockey_stick, hospital, hot_air_balloon, hot_dog, hot_tub, hourglass, house, house_plant, hurricane, ice_cream, jacket, jail, kangaroo, key, keyboard, knee, knife, ladder, lantern, laptop, leaf, leg, light_bulb, lighter, lighthouse, lightning, line, lion, lipstick, lobster, lollipop, mailbox, map, marker, matches, megaphone, mermaid, microphone, microwave, monkey, moon, mosquito, motorbike, mountain, mouse, moustache, mouth, mushroom, nail, necklace, nose, ocean, octagon, octopus, onion, oven, owl, paintbrush, paint_can, palm_tree, panda, pants, paper_clip, parachute, parrot, passport, peanut, pear, peas, pencil, penguin, piano, pickup_truck, picture_frame, pig, pillow, pineapple, pizza, pliers, police_car, pond, pool, popsicle, postcard, potato, power_outlet, purse, rabbit, raccoon, radio, rain, rainbow, rake, remote_control, rhinoceros, rifle, river, roller_coaster, rollerskates, sailboat, sandwich, saw, saxophone, school_bus, scissors, scorpion, screwdriver, sea_turtle, see_saw, shark, sheep, shoe, shorts, shovel, sink, skateboard, skull, skyscraper, sleeping_bag, smiley_face, snail, snake, snorkel, snowflake, snowman, soccer_ball, sock, speedboat, spider, spoon, spreadsheet, square, squiggle, squirrel, stairs, star, steak, stereo, stethoscope, stitches, stop_sign, stove, strawberry, streetlight, string_bean, submarine, suitcase, sun, swan, sweater, swing_set, sword, syringe, table, teapot, teddy-bear, telephone, television, tennis_racquet, tent, the_eiffel_tower, the_great_wall_of_china, the_mona_lisa, tiger, toaster, toe, toilet, tooth, toothbrush, toothpaste, tornado, tractor, traffic_light, train, tree, triangle, trombone, truck, trumpet, t-shirt, umbrella, underwear, van, vase, violin, washing_machine, watermelon, waterslide, whale, wheel, windmill, wine_bottle, wine_glass, wristwatch, yoga, zebra, zigzag
