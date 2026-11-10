# 메뉴 일러스트

2026-11-10 · 내장 `image_gen` 도구로 제작. 사용자가 제공한 양피지 메뉴판은 그림체·제품 참고 자료이며, 새 이미지에는 글자·가격·판넬을 넣지 않았습니다. 원본을 확인한 뒤 WebP로 인코딩해 구매자 메뉴와 담당자 수기판매에서 함께 사용합니다. 실제 제품 사진을 받으면 `server/catalog.py`의 `PRODUCT_PHOTOS` 경로를 교체합니다.

| 메뉴 ID | 프로젝트 파일 |
| --- | --- |
| 101 | [plain-financier-v1.webp](../frontend/assets/products/plain-financier-v1.webp) |
| 102 | [chocolate-financier-v1.webp](../frontend/assets/products/chocolate-financier-v1.webp) |
| 103 | [caramel-financier-v1.webp](../frontend/assets/products/caramel-financier-v1.webp) |
| 104 | [fig-financier-v1.webp](../frontend/assets/products/fig-financier-v1.webp) |
| 105 | [lotus-brownie-cheesecake-v1.webp](../frontend/assets/products/lotus-brownie-cheesecake-v1.webp) |
| 106 | [lemon-dacquoise-v1.webp](../frontend/assets/products/lemon-dacquoise-v1.webp) |
| 107 | [earl-grey-dacquoise-v1.webp](../frontend/assets/products/earl-grey-dacquoise-v1.webp) |
| 108 | [glazed-donut-set-v1.webp](../frontend/assets/products/glazed-donut-set-v1.webp) |
| 109 | [chestnut-madeleine-v1.webp](../frontend/assets/products/chestnut-madeleine-v1.webp) |
| 110 | [egg-tart-v1.webp](../frontend/assets/products/egg-tart-v1.webp) |
| 111 | [cheese-tart-v1.webp](../frontend/assets/products/cheese-tart-v1.webp) |

## 최종 생성 프롬프트

<details>
<summary>101 · plain-financier-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Subject: one PLAIN FINANCIER, a small rectangular French almond butter cake with a smooth golden top, crisp darker browned edges, softly domed center and a fine baked crumb. Absolutely no chocolate, drizzle or fruit toppings. A tiny almond beside it is acceptable, but keep the financier dominant.
```

</details>

<details>
<summary>102 · chocolate-financier-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art direction; Image 2 is an approved product illustration, to match its bright parchment, framing, scale and rendering. Draw ONLY the requested product, not the menu sheet or the plain financier from image 2.
Subject: one CHOCOLATE FINANCIER, a small rectangular cocoa almond cake, rich deep cocoa brown throughout, crisp baked ridges and darker browned edges. No golden plain cake, no fruit. Use a tiny cocoa bean as a subtle flavor cue.
```

</details>

<details>
<summary>103 · caramel-financier-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art direction; Image 2 is an approved product illustration, to match its bright parchment, framing, scale and rendering. Draw ONLY the requested product, not the menu sheet or the plain financier from image 2.
Subject: one CARAMEL FINANCIER, a small rectangular amber-brown almond cake with glossy thin caramel stripes crossing its golden baked top. Distinct toffee color, not dark chocolate. A tiny caramel shard beside it is a subtle flavor cue.
```

</details>

<details>
<summary>104 · fig-financier-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art direction; Image 2 is an approved product illustration, to match its bright parchment, framing, scale and rendering. Draw ONLY the requested product, not the menu sheet or the plain financier from image 2.
Subject: one FIG FINANCIER, a small rectangular golden almond cake with exactly three recognizable round dried-fig cross sections embedded in the top, visible pinkish-brown seeds and pale rims. No caramel drizzle and no chocolate. A small dried fig beside it is a subtle flavor cue.
```

</details>

<details>
<summary>105 · lotus-brownie-cheesecake-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art direction and product guide; Image 2 is an approved illustration to match bright parchment, scale, hatching and painting. Draw ONLY the requested product, not a financier.
Subject: one square LOTUS BISCOFF BROWNIE CHEESECAKE slice. A dense dark chocolate brownie base, a thick creamy pale cheesecake layer with caramel-colored swirls, and one small embossed caramel biscuit resting on top. The biscuit has a decorative pattern but absolutely NO words or logos. The layers should be obvious in a three-quarter view. No book or other fantasy prop.
```

</details>

<details>
<summary>106 · lemon-dacquoise-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art direction and product guide; Image 2 is an approved illustration to match bright parchment, scale, hatching and painting. Draw ONLY the requested product, not a financier.
Subject: one LEMON DACQUOISE sandwich pastry, two round golden almond meringue shells with a craggy delicate surface, generous light yellow lemon cream visible in the middle. Place a small lemon wedge and a tiny leaf beside it so lemon is immediately recognizable. The pastry is yellow-gold, not a smooth macaron shell.
```

</details>

<details>
<summary>107 · earl-grey-dacquoise-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art direction and product guide; Image 2 is an approved illustration to match bright parchment, scale, hatching and painting. Draw ONLY the requested product, not a financier.
Subject: one EARL GREY DACQUOISE sandwich pastry, two round beige almond meringue shells visibly speckled with fine dark tea, light brown tea cream in the middle. A very small pinch of loose black tea and a tea leaf beside it identifies Earl Grey. No lemon, no yellow cream. Textured dacquoise shells, not smooth macarons.
```

</details>

<details>
<summary>108 · glazed-donut-set-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art and product guide; Image 2 establishes consistent bright parchment, framing, hatching and painting. Draw ONLY the requested product, not a financier.
Subject: exactly FIVE small round holeless glazed donut balls, arranged as two at the back and three at the front, all five individually countable. Warm golden fried dough and a thin shiny clear sugar glaze. Follow the five gold spheres in the original reference but make them look like real delicious donut bites, not metal or fruit. No rings or holes. No extra pastry.
```

</details>

<details>
<summary>109 · chestnut-madeleine-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art and product guide; Image 2 establishes consistent bright parchment, framing, hatching and painting. Draw ONLY the requested product, not a financier.
Subject: one CANDIED CHESTNUT MADELEINE, a small plump chestnut-shaped butter cake with clearly sculpted vertical madeleine flutes, appetizing golden-brown baked cake surface and darker brown candied chestnut detail at the tip. A small glossy candied chestnut piece alongside it signals the flavor. It must unmistakably look like a baked madeleine cake, NOT a raw chestnut, tree or fruit illustration. No chocolate coating.
```

</details>

<details>
<summary>110 · egg-tart-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art and product guide; Image 2 establishes the bright parchment, framing, hatching and painting. Draw ONLY the requested tart, not a financier.
Subject: one EGG TART in a small golden fluted tart shell, with a glossy vivid golden-yellow egg custard surface and several characteristic dark caramelized toasted spots. Side angle reveals crisp layered pastry and soft custard. Keep the tart dominant; no plate, furnace, book or separate egg props.
```

</details>

<details>
<summary>111 · cheese-tart-v1.webp</summary>

```text
Use case: style-transfer. Transform the supplied bakery menu sheet into ONE standalone product illustration for a small bakery menu thumbnail. The input sheet is a STYLE AND PRODUCT REFERENCE, not a layout to reproduce. Match its antique alchemist cookbook artwork: warm sepia ink hatching, delicate hand-painted shading, appetizing golden baked textures, soft ivory parchment, restrained botanical etching. Square composition. A single food subject in a three-quarter view fills about 75% of the canvas, clearly identifiable at small sizes. Background is pale warm parchment with only a faint contact shadow; keep it calm and bright. No typography, no prices, no labels, no border, no split panels, no book, no furnace, no tree, no watermark. Do not depict the whole reference poster.
Reference roles: Image 1 is the original art and product guide; Image 2 establishes the bright parchment, framing, hatching and painting. Draw ONLY the requested tart, not a financier.
Subject: one CHEESE TART in a small golden fluted tart shell. Its creamy pale ivory-yellow cheesecake filling is smoothly domed, lightly toasted warm gold at the edge, with an even soft center and NO dark burnt custard spots. It should look clearly different from a Portuguese egg tart, more creamy and pale. No plate, furnace, book or extra props.
```

</details>
