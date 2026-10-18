"""The one running case of every test: a cat café in Tunis, the brief its owner confirmed, the ten pages Tavily
returns for it and the four rows the model reads out of them."""

from contracts.brief import Brief
from contracts.researcher import Page, Row, Rows

BRIEF = Brief(
    idea="café where customers sit with resident cats, drinks and pastries",
    place="Tunis",
    a_angles=["cat café", "pet-friendly café"],
)

PAGES = [
    Page(
        url="https://chatscafe.tn/",
        title="Chats Café La Marsa",
        text="Chats Café, La Marsa. Coffee and cake among our twelve cats. Espresso 4.5 TND. Open every day.",
    ),
    Page(
        url="https://www.instagram.com/pawsandbeans/",
        title="Paws & Beans",
        text="Paws & Beans, Lac 2. Pet-friendly terrace, bring your dog. Cappuccino 6 TND. Order online.",
    ),
    Page(
        url="https://tunis-guide.example/best-cafes",
        title="10 best cafés in Tunis",
        text="Le Chat Noir on avenue Habib Bourguiba, a classic café with a cat on the sign, no real cats. "
        "Café des Nattes in Sidi Bou Said, mint tea with pine nuts. El Ali in the medina, rooftop.",
    ),
    Page(
        url="https://cafedesnattes.example/",
        title="Café des Nattes",
        text="Café des Nattes, Sidi Bou Said. Tea and coffee since 1920.",
    ),
    Page(
        url="https://elali.example/",
        title="El Ali",
        text="El Ali, medina of Tunis. Restaurant and café, rooftop terrace.",
    ),
    Page(
        url="https://tunisia-living.example/pets",
        title="Pets in Tunisia",
        text="Where to go with your pet in Tunis: parks, vets, and a few terraces.",
    ),
    Page(url="https://www.facebook.com/lecatcafe.tunis", title="Le Cat Café Tunis", text="Coming soon."),
    Page(
        url="https://delices.example/",
        title="Délices de Tunis",
        text="Délices de Tunis, pastries and coffee, Ariana. Mille-feuille 3 TND.",
    ),
    Page(url="https://cafes-tunis.example/menzah", title="Cafés in El Menzah", text="A list of cafés in El Menzah 6."),
    Page(url="https://spca.example/tunis", title="Animal shelter Tunis", text="Adopt a cat. Open Saturdays."),
]

# What the model answers for the pages above: three real rows and Kitty Corner, which is on no page.
MODEL_ROWS = Rows(
    rows=[
        Row(
            name="Chats Café",
            offer="coffee and cake among resident cats",
            price="espresso 4.5 TND",
            channel="shop",
            page_no=1,
            kind="direct",
        ),
        Row(
            name="Paws & Beans",
            offer="pet-friendly terrace café",
            price="cappuccino 6 TND",
            channel="both",
            page_no=2,
            kind="indirect",
        ),
        Row(name="Le Chat Noir", offer="classic café", price=None, channel="shop", page_no=3, kind="indirect"),
        Row(name="Kitty Corner", offer="cat café", price=None, channel="shop", page_no=3, kind="direct"),
    ]
)
