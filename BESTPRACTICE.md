# PPTAgent Best Practices Guide 💪

PPTAgent is designed to support the generation of high-quality slides using any unlabeled slides as references.

However, the complexity of real-world slides may affect its applicability and the quality of the generated slides.

This document details, from three aspects: **[Parsing Limitations](#1-parsing-limitations-)**, **[Reference Slide Design Guidelines](#2-reference-slide-design-guidelines-)**, and **[Parameter Settings](#3-parameter-settings-and-parsing-)**, how to provide high-quality reference slides to maximize PPTAgent's generation effectiveness.

-----

## 1\. Parsing Limitations 👿

PPTAgent relies on `python-pptx` for presentation parsing, but this library has the following limitations, causing some elements to be parsed incorrectly:

  - **Unsupported Elements**:
      - Nested Group Shapes (Nested GroupShape)
      - Freeform Shapes (Freeform)
      - Video/Audio (Video/Sound)
      - Other complex elements

**Handling**: Slides containing the above elements will be skipped, and relevant information will be recorded in the logging output.

**Recommendation**: When preparing reference presentations, try to avoid using the complex elements mentioned above to ensure smooth parsing.

-----

## 2\. Reference Slide Design Guidelines 🎨

To improve the generation quality of PPTAgent, reference slides better adhere to the following design guidelines:

### 2.1 Textframe Styles

Due to limitations in `python-pptx`, some style attributes cannot be modified. Thus we recommend setting all textframes to **Shrink text on overflow** to ensure better text content adaptability.

### 2.2 Layout and Element

PPTAgent does not involve creating new slide layouts or modifying styles, so the following design principles are recommended:

  - **Simple Layout**: Each slide better contain no more than **6 elements** to maintain simplicity.
  - **Space Utilization**: Elements should effectively use surrounding white space, leaving flexibility for content adjustments.
  - **Content Hierarchy**: Content at the same level should be placed within the **same slide element**. For example, table of contents items should be represented using bullet points (bullets) rather than multiple separate elements.
  - **Text Amount Control**: The amount of text in each slide element is recommended to occupy about **60%** of the element's space. PPTAgent can control the text amount of the generated slides based on the original text length of the reference slide elements using the `length_factor` parameter (see Parameter Settings for details).

### 2.3 Functional Layout Constraints

Although the paper utilizes unconstrained functional layout extraction, to enhance the structural integrity of the generated slides, PPTAgent now constrains slide functional layouts to the following four types: Opening, Table of Contents, Section Header, and Ending.

**Recommendation**: Reference slides should include at least a **Opening Page** and an **Ending Page**. PPTAgent will intersperse these four layout types into the generated slides using a rule-based method.

### 2.4 Background Images

Images with a relative area coverage exceeding **95%** will be considered background images. Additionally, the `hide_small_pic_ratio` parameter can be adjusted to treat more small images as background images.

-----

## 3\. Parameter Settings 🔍

PPTAgent provides the following parameters to control slide generation behavior:

> Note: The value ranges below are recommended ranges; they can be adjusted based on actual needs during use.

  - **`num_slides: int`**

      - **Function**: Controls the number of content slides to be generated. Note that functional slides (Title, TOC, Section Header, Ending) are inserted using a rule-based method and are not constrained by this parameter.
      - **Value Range**: `[4, 32]`, no default value.

  - **`length_factor: float`**

      - **Function**: Controls the text length of the generated slides by comparing it to the text amount in the reference slides.
      - **Value Range**: `[0.5, 2.5]`, default value is `None` (length is not controlled).
      - **Recommendation**: Adjust based on the desired level of detail for the target slides. For example, `1.0` means the text amount will be consistent with the reference slides. When the language of the reference slides differs from the input document's language, adjust this parameter accordingly. For instance, if the input document is Chinese and the reference slides are English, setting this parameter to `0.5` is recommended. If the input document is English and the reference slides are Chinese, setting it to `2.0` is recommended.

  - **`hide_small_pic_ratio: float`**

      - **Function**: Images whose area relative to the slide area is smaller than this value are considered "small images".
      - **Value Range**: `[0, 0.5]`, default value is `0.2` (i.e., images covering less than 20% of the slide area are considered small images).

  - **`keep_in_background: bool`**

      - **Function**: Determines how small images are handled.
          - `True`: Small images will be placed in the background.
          - `False`: Small images will be ignored.

 - **`sim_bound: float`**

      - **Function**: Controls the similarity threshold for document retrieval.
      - **Value Range**: `[0.3, 0.9]`, default value is `0.5`.
      - **Recommendation**: Adjust based on the desired similarity level for the document retrieval.

 - **`error_exit: bool`**

      - **Function**: Whether to exit when a slide failed to generate.
      - **Value Range**: `[True, False]`, default value is `False`.
