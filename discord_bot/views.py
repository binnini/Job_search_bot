import discord
from db.io import save_subscription, get_subscriptions, MAX_SUBSCRIPTIONS_PER_USER
from db.JobPreprocessor import JobPreprocessor


def _describe_subscription(sub) -> str:
    parts = []
    if sub.keyword:
        parts.append(f"키워드: {sub.keyword}")
    if sub.region:
        parts.append(f"지역: {sub.region}")
    if sub.form is not None:
        parts.append(f"고용형태: {JobPreprocessor.stringify_form(sub.form)}")
    if sub.max_experience is not None:
        parts.append(f"최대경력: {JobPreprocessor.stringify_experience(sub.max_experience)}")
    if sub.min_annual_salary is not None:
        parts.append(f"최소연봉: {JobPreprocessor.stringify_salary(sub.min_annual_salary)}")
    return ", ".join(parts) if parts else "(조건 없음)"


class KeywordModal(discord.ui.Modal, title="직군 키워드 입력"):
    keyword_input = discord.ui.TextInput(
        label="키워드",
        placeholder="예: 백엔드, Python, 데이터엔지니어",
        required=False,
        max_length=100,
    )

    def __init__(self, view: "SubscriptionView"):
        super().__init__()
        self.sub_view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.sub_view.keyword = self.keyword_input.value.strip() or None
        label = f"`{self.sub_view.keyword}`" if self.sub_view.keyword else "없음"
        await interaction.response.send_message(
            f"키워드 설정됨: {label}", ephemeral=True
        )


class SubscriptionView(discord.ui.View):
    def __init__(self, discord_user_id: str):
        super().__init__(timeout=300)
        self.discord_user_id = discord_user_id
        self.region = None
        self.form = None
        self.max_experience = None
        self.min_annual_salary = None
        self.keyword = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.discord_user_id:
            await interaction.response.send_message(
                "본인의 구독 설정만 조작할 수 있습니다.", ephemeral=True
            )
            return False
        return True

    @discord.ui.select(
        placeholder="📍 희망 근무지",
        row=0,
        options=[
            discord.SelectOption(label="상관없음", value="none", default=True),
            discord.SelectOption(label="서울", value="서울"),
            discord.SelectOption(label="경기", value="경기"),
            discord.SelectOption(label="인천", value="인천"),
            discord.SelectOption(label="부산", value="부산"),
            discord.SelectOption(label="대구", value="대구"),
            discord.SelectOption(label="광주", value="광주"),
            discord.SelectOption(label="대전", value="대전"),
            discord.SelectOption(label="울산", value="울산"),
            discord.SelectOption(label="세종", value="세종"),
            discord.SelectOption(label="강원", value="강원"),
            discord.SelectOption(label="충북", value="충북"),
            discord.SelectOption(label="충남", value="충남"),
            discord.SelectOption(label="전북", value="전북"),
            discord.SelectOption(label="전남", value="전남"),
            discord.SelectOption(label="경북", value="경북"),
            discord.SelectOption(label="경남", value="경남"),
            discord.SelectOption(label="제주", value="제주"),
        ],
    )
    async def region_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        self.region = None if select.values[0] == "none" else select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="💼 희망 고용형태",
        row=1,
        options=[
            discord.SelectOption(label="상관없음", value="none", default=True),
            discord.SelectOption(label="정규직", value="정규직"),
            discord.SelectOption(label="계약직", value="계약직"),
            discord.SelectOption(label="인턴", value="인턴"),
            discord.SelectOption(label="프리랜서", value="프리랜서"),
            discord.SelectOption(label="아르바이트", value="아르바이트"),
        ],
    )
    async def form_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        val = select.values[0]
        self.form = None if val == "none" else JobPreprocessor.parse_form(val)
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="📅 최대 경력",
        row=2,
        options=[
            discord.SelectOption(label="상관없음", value="none", default=True),
            discord.SelectOption(label="신입", value="0"),
            discord.SelectOption(label="1년 이하", value="1"),
            discord.SelectOption(label="3년 이하", value="3"),
            discord.SelectOption(label="5년 이하", value="5"),
            discord.SelectOption(label="10년 이하", value="10"),
        ],
    )
    async def experience_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        val = select.values[0]
        self.max_experience = None if val == "none" else int(val)
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="💰 최소 연봉",
        row=3,
        options=[
            discord.SelectOption(label="상관없음", value="none", default=True),
            discord.SelectOption(label="2000만원 이상", value="2000"),
            discord.SelectOption(label="3000만원 이상", value="3000"),
            discord.SelectOption(label="4000만원 이상", value="4000"),
            discord.SelectOption(label="5000만원 이상", value="5000"),
            discord.SelectOption(label="6000만원 이상", value="6000"),
        ],
    )
    async def salary_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        val = select.values[0]
        self.min_annual_salary = None if val == "none" else int(val)
        await interaction.response.defer()

    @discord.ui.button(label="키워드 입력", style=discord.ButtonStyle.secondary, row=4)
    async def keyword_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(KeywordModal(self))

    @discord.ui.button(label="구독 등록", style=discord.ButtonStyle.primary, row=4)
    async def submit_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if all(
            v is None
            for v in [
                self.region,
                self.form,
                self.max_experience,
                self.min_annual_salary,
                self.keyword,
            ]
        ):
            await interaction.response.send_message(
                "❌ 조건을 하나 이상 선택해주세요.", ephemeral=True
            )
            return

        ok, err = save_subscription(
            discord_user_id=self.discord_user_id,
            keyword=self.keyword,
            region=self.region,
            form=self.form,
            max_experience=self.max_experience,
            min_annual_salary=self.min_annual_salary,
        )
        if not ok:
            await interaction.response.send_message(f"❌ {err}", ephemeral=True)
            return

        subs = get_subscriptions(self.discord_user_id)
        new_sub = subs[-1]
        await interaction.response.edit_message(
            content=(
                f"✅ 구독이 등록되었습니다! ({len(subs)}/{MAX_SUBSCRIPTIONS_PER_USER}개)\n"
                f"{_describe_subscription(new_sub)}\n"
                f"조건에 맞는 신규 공고가 올라오면 DM으로 알려드립니다."
            ),
            view=None,
        )
        self.stop()

    async def on_timeout(self):
        # 타임아웃 시 컴포넌트 비활성화
        for item in self.children:
            item.disabled = True
