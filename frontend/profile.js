// Stored profiles contain option names only; all drawing paths and colors stay local.
export const avatarOptions = {
  face_shape: [['madeleine','마들렌'],['financier','휘낭시에'],['pound','파운드케이크']],
  skin: [['light','살짝 구움','#fff0c2'],['warm','노릇노릇','#edbc70'],['deep','바삭하게','#c8894c']],
  expression: [['smile','방긋'],['happy','활짝'],['wink','윙크'],['surprised','깜짝']],
  glasses: [['none','안경 없음'],['round','동그란 안경'],['square','네모 안경'],['sunglasses','멋진 선글라스']],
  hairpin: [['none','머리핀 없음'],['bread_101','플레인 휘낭시에'],['bread_102','초코 휘낭시에'],
    ['bread_103','카라멜 휘낭시에'],['bread_104','무화과 휘낭시에'],['bread_105','로투스 브라우니 치즈케이크'],
    ['bread_106','레몬 다쿠아즈'],['bread_107','얼그레이 다쿠아즈'],['bread_108','글레이즈드 도넛 5개 세트'],
    ['bread_109','보늬밤 마들렌'],['bread_110','에그타르트'],['bread_111','치즈타르트']],
};

const safe = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const legacyFaces={round:'madeleine',oval:'financier',square:'pound',soboro:'madeleine',salt:'financier',toast:'pound'};
export const badgeIcons=[['spark','반짝임'],['flask','마법 물약'],['star','별'],['heart','하트'],['bread','빵'],['trophy','트로피']];
export function badgePicture(badge,{className='',decorative=true}={}){
  const artwork={ach_elements:'elements',ach_vvip:'vvip',ach_focus:'focus',ach_fast:'fast'}[badge?.id];
  if(artwork)return `<img class="badge-picture badge-art ${safe(className)}" data-badge-id="${safe(badge.id)}" src="/assets/badges/${artwork}-v1.webp" alt="${decorative?'':safe(badge.name)}" width="40" height="40" loading="lazy" ${decorative?'aria-hidden="true"':''}>`;
  const icons={spark:'<path d="m20 9 3 8 8 3-8 3-3 8-3-8-8-3 8-3Z"/>',
    flask:'<path d="M16 10h8m-6 1v8l-6 10q8 5 16 0l-6-10v-8M15 25h10"/>',
    star:'<path d="m20 9 3.4 7 7.6 1.1-5.5 5.3 1.3 7.6-6.8-3.6-6.8 3.6 1.3-7.6L9 17.1l7.6-1.1Z"/>',
    heart:'<path d="M20 30 10 20c-6-8 5-14 10-7 5-7 16-1 10 7Z"/>',
    bread:'<path d="M12 20C5 13 16 7 20 12c5-5 15 1 8 8v10H12Z"/><path d="M17 20v5m6-5v5"/>',
    trophy:'<path d="M14 11h12v10a6 6 0 0 1-12 0Zm0 3H9v4q0 6 6 6m11-10h5v4q0 6-6 6m-5 3v5m-5 0h10"/>'};
  const key=Object.hasOwn(icons,badge?.icon)?badge.icon:'spark';
  const colors={spark:['#fff0b2','#b37820'],flask:['#dceef9','#4c7e9b'],star:['#e9e0fa','#7c5b9d'],heart:['#fbe0e4','#b96379'],bread:['#fae1b8','#a66e34'],trophy:['#e1efce','#67854a']};
  const [fill,stroke]=colors[key];
  return `<svg xmlns="http://www.w3.org/2000/svg" class="badge-picture ${safe(className)}" data-badge-id="${safe(badge?.id||'')}" viewBox="0 0 40 40" width="40" height="40" ${decorative?'aria-hidden="true"':`role="img" aria-label="${safe(badge?.name||'배지')}"`}><circle cx="20" cy="20" r="19" fill="#fff"/><circle cx="20" cy="20" r="16.5" fill="${fill}" stroke="${stroke}" stroke-width="1.4"/><g fill="${fill}" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${icons[key]}</g></svg>`;
}
export const titleStyles=[['magic','마법빛'],['gold','황금빛'],['lightning','번개']];
export function profileTitle(user={}){
  if(user.role==='staff'||user.profile_kind==='admin')return '';
  const title=user.equipped_title;
  if(!title)return '';
  const style=titleStyles.some(([key])=>key===title.style)?title.style:'magic';
  return `<span class="profile-title title-${style}" title="${safe(title.name)}"><i aria-hidden="true">✦</i><span>${safe(title.name)}</span><i aria-hidden="true">✧</i></span>`;
}
export function normalizeAvatar(value, userId=0) {
  const seed = Math.max(0,Math.floor(Number(userId)||0));
  return Object.fromEntries(Object.entries(avatarOptions).map(([key,choices])=>{
    const fixed={expression:'smile',glasses:'none',hairpin:'none'};
    const fallback = Object.hasOwn(fixed,key) ? fixed[key] : choices[seed % choices.length][0];
    const raw=value?.[key];
    const selected=key==='face_shape'&&typeof raw==='string'&&Object.hasOwn(legacyFaces,raw)?legacyFaces[raw]:raw;
    return [key,choices.some(([id])=>id===selected) ? selected : fallback];
  }));
}

export function profileAvatar(user={}, {className='',full=false,level=null,label,decorative=false,breadOnly=false,pinOnly=false}={}) {
  if(user.role==='staff'||user.profile_kind==='admin')return `<img class="profile-avatar admin-avatar ${safe(className)}" src="/assets/admin-avatar-v1.svg" alt="${decorative?'':safe(label||'관리자 공용 프로필')}" width="40" height="40">`;
  const a=normalizeAvatar(user.avatar,user.id);
  const skin=avatarOptions.skin.find(([id])=>id===a.skin)[2];
  const crust={light:'#ce9149',warm:'#b87a3c',deep:'#965a31'}[a.skin];
  const crumb={light:'#fff4d5',warm:'#f4d69a',deep:'#e7be7d'}[a.skin];
  const tier=Number.isInteger(level) ? Math.max(0,Math.min(5,level)) : 0;
  const robe=['#7e9b79','#7e9b79','#719cad','#c9a75e','#9b80b3','#655880'][tier];
  const face={
    madeleine:`<path d="M61 87Q51 78 61 69Q60 56 74 58Q80 45 91 54Q100 43 109 54Q122 46 126 59Q140 57 139 71Q150 80 139 92L125 117Q113 130 100 134Q87 130 75 117Z" fill="${skin}"/>
      <g fill="none" stroke="${crust}" stroke-width="2"><path d="M69 77Q69 99 85 119M81 65Q80 75 85 83M100 59v22M119 65Q120 75 115 83M131 77Q131 99 115 119M93 122l7 9 7-9"/></g>
      <path d="M69 71q3-9 10-6M89 59q10-8 20 0M123 66q7 0 9 7" fill="none" stroke="${crumb}" stroke-width="3"/>`,
    financier:`<rect x="57" y="68" width="86" height="61" rx="8" fill="${crust}"/>
      <rect x="63" y="74" width="74" height="49" rx="5" fill="${skin}" stroke="none"/>
      <path d="M67 79h66M63 116q37 8 74 0M62 73l5 5M138 73l-5 5" fill="none" stroke="${crust}" stroke-width="1.7" opacity=".6"/>
      <path d="M72 82h17M118 82h9" stroke="${crumb}" stroke-width="3"/>
      <g fill="${crust}" opacity=".4" stroke="none"><circle cx="68" cy="98" r="1.6"/><circle cx="133" cy="103" r="1.8"/><circle cx="90" cy="120" r="1.5"/><circle cx="112" cy="120" r="1.3"/></g>`,
    pound:`<path d="M61 78Q56 59 76 54Q100 39 124 54Q144 59 139 78V120Q139 130 129 130H71Q61 130 61 120Z" fill="${crust}"/>
      <path d="M69 79Q65 67 80 63Q100 51 120 63Q135 67 131 79V121H69Z" fill="${crumb}" stroke="none"/>
      <path d="M74 61q13 10 26 2 13 8 26-2" fill="none" stroke="${skin}" stroke-width="3"/>
      <g fill="${crust}" opacity=".32" stroke="none"><circle cx="78" cy="81" r="2"/><circle cx="121" cy="81" r="2.3"/><circle cx="77" cy="114" r="1.8"/><circle cx="124" cy="112" r="2"/><circle cx="111" cy="117" r="1.4"/><circle cx="104" cy="77" r="1.6"/></g>`,
  }[a.face_shape];
  const glasses=a.glasses==='none'?'':a.glasses==='sunglasses'?'<g class="cool-sunglasses" stroke="#353544" stroke-width="3"><path d="M67 86h29l-3 17q-12 8-23-1Zm37 0h29l-3 16q-11 9-23 1Z" fill="#414455"/><path d="M96 90h8M67 88l-6-4M133 88l6-4" fill="none"/><path d="m75 90 7 8m31-8 7 8" stroke="#b2c1d1" stroke-width="2"/></g>':`<g fill="none" stroke="#514247" stroke-width="3">${a.glasses==='round'?'<circle cx="82" cy="94" r="12"/><circle cx="118" cy="94" r="12"/>':'<rect x="69" y="84" width="26" height="21" rx="5"/><rect x="105" y="84" width="26" height="21" rx="5"/>'}<path d="M95 93Q100 89 105 93M69 91 63 88M131 91 137 88"/></g>`;
  const pastryPin=()=>{
    const id=Number(a.hairpin.replace('bread_',''));
    if(a.hairpin==='none')return '';
    let charm='';
    if(id>=101&&id<=104){
      const fill={101:'#efc575',102:'#795047',103:'#c78b49',104:'#d6ad79'}[id];
      charm=`<rect x="119" y="75" width="23" height="15" rx="3" fill="${fill}"/><path d="M122 78h17M122 87h17" fill="none" opacity=".5"/>`;
      if(id===104)charm+='<path d="M130 76q-9 9 0 12 9-3 0-12Z" fill="#a86779"/><path d="M130 79v6" stroke="#f7d1a4"/>';
    }else if(id===105){
      charm='<path d="m119 78 17-5 8 14-23 4Z" fill="#f1cd87"/><path d="m121 84 20-5 3 8-23 4Z" fill="#765043"/><path d="m120 78 17-4 3 5-19 5Z" fill="#ba8b57"/>';
    }else if(id===106||id===107){
      charm=`<path d="M118 82q3-10 13-9 13 1 14 9-3 10-14 10-11 0-13-10Z" fill="${id===106?'#f1d27e':'#c6b0a3'}"/><path d="M120 83h23" stroke="${id===106?'#fff3bf':'#8b7468'}" stroke-width="3"/>`;
    }else if(id===108){
      charm='<circle cx="131" cy="82" r="11" fill="#db9a53"/><circle cx="131" cy="82" r="4" fill="#f4f0e5"/><path d="M122 78q8-9 17-1" fill="none" stroke="#fff0ce" stroke-width="3"/>';
    }else if(id===109){
      charm='<path d="M120 78q-2-6 4-5 4-6 8-1 7-3 9 3 6 2 2 8l-12 11Z" fill="#e4b46a"/><path d="m125 78 6 12 6-12M131 77v11" fill="none" stroke="#b98042"/>';
    }else if(id===110||id===111){
      charm=`<path d="m118 80 5-6 8 2 8-2 5 7-4 10h-19Z" fill="#cf9958"/><ellipse cx="131" cy="82" rx="9" ry="6" fill="${id===110?'#f3cd68':'#fff0b8'}"/>`;
      if(id===110)charm+='<path d="m128 79 4-1 3 3-4 2Z" fill="#b87944" stroke="none"/>';
    }
    const tilt=id>=101&&id<=104?' transform="rotate(-25 131 82)"':'';
    return `<g class="bread-hairpin" data-pin-product="${id}"${tilt} stroke="#78563e" stroke-width="1.5"><path d="M118 89h26" stroke="#b89867" stroke-width="3"/>${charm}</g>`;
  };
  const pin=pastryPin();
  const hat=tier===5?`<path d="m72 54 1-22 17 10 10-20 12 20 17-10-1 22Z" fill="#e6c373"/><path d="M72 55Q100 49 128 55L126 64Q100 59 74 64Z" fill="#f8e0a1"/>`:`<path d="m70 54 24-37 30 38Z" fill="${robe}"/><path d="M67 54Q100 48 132 55L128 64Q101 58 71 63Z" fill="#d4dcc2"/><path d="m94 31 3 7 7 1-6 4 1 7-6-4-6 4 2-7-6-4 8-1Z" fill="#ffe2a0" stroke="none"/>`;
  const badge=!breadOnly&&!pinOnly?user.equipped_badge:null;
  const name=label||`${user.name||'연금술사'}의 프로필 캐릭터${badge?` · ${badge.name} 배지`:''}`;
  const emotion={
    smile:'<path d="M82 92V96M118 92V96" stroke-width="4"/><path d="M93 108Q100 115 107 108" fill="none"/>',
    happy:'<path d="M76 96q6-9 12 0m24 0q6-9 12 0" fill="none" stroke-width="3"/><path d="M91 107q9 4 18 0 1 14-9 14-10 0-9-14Z" fill="#985b48"/><path d="M95 117q5-4 10 0" fill="none" stroke="#e6a58c"/>',
    wink:'<path d="M82 92v4M122 91l-8 4 8 4" fill="none" stroke-width="3.5"/><path d="M93 108q8 9 17-1" fill="none"/>',
    surprised:'<circle cx="82" cy="94" r="3" fill="#55434c" stroke="none"/><circle cx="118" cy="94" r="3" fill="#55434c" stroke="none"/><path d="M77 85q5-4 10 0m26 0q5-4 10 0" fill="none" stroke-width="2"/><ellipse cx="100" cy="113" rx="5" ry="6" fill="#985b48"/>',
  }[a.expression];
  const expression=`${emotion}
      <path d="m98 102 2-2 3 3-3 2Z" fill="${crust}" stroke="none"/>
      <ellipse cx="77" cy="105" rx="7" ry="4" fill="#e59482" opacity=".65" stroke="none"/>
      <ellipse cx="123" cy="105" rx="7" ry="4" fill="#e59482" opacity=".65" stroke="none"/>`;
  const attributes=`xmlns="http://www.w3.org/2000/svg" class="profile-avatar ${safe(className)}" data-bread-face="${a.face_shape}" data-expression="${a.expression}" ${decorative?'aria-hidden="true" focusable="false"':`role="img" aria-label="${safe(name)}"`}`;
  if(pinOnly)return `<svg ${attributes} viewBox="113 67 37 31">${pin||'<circle cx="131" cy="82" r="11" fill="none" stroke="#bdb5a5" stroke-width="2"/><path d="m123 74 16 16" stroke="#bdb5a5" stroke-width="2"/>'}</svg>`;
  if(breadOnly)return `<svg ${attributes} viewBox="40 44 120 94"><g stroke="#55434c" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">${face}${expression}</g></svg>`;
  const drawing=`<svg ${attributes} viewBox="${full?'0 0 200 200':'35 25 130 130'}" ${level===null?'':`data-character-level="${tier}"`}>
    <circle cx="100" cy="100" r="96" fill="#f4f0e5"/>
    <g stroke="#55434c" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <ellipse cx="100" cy="183" rx="57" ry="7" fill="#665079" opacity=".09" stroke="none"/>
      <path d="M78 165 76 181Q85 187 94 181L95 166M105 166 106 181Q116 187 125 181L122 165" fill="#6c5552"/>
      <path d="M79 118Q100 111 121 118L135 173Q100 182 65 173Z" fill="${robe}"/>
      <path d="M78 122Q63 123 55 149L66 155 84 133M122 122Q137 123 145 149L134 155 116 133" fill="${robe}"/>
      <circle cx="58" cy="152" r="9" fill="${skin}"/><circle cx="142" cy="152" r="9" fill="${skin}"/>
      <path d="M82 120 100 135 118 120M100 136V173" fill="none" stroke="#fff4c9" stroke-width="3"/>
      <circle cx="100" cy="136" r="5" fill="#edc36c"/>
      ${face}
      ${expression}
      ${glasses}${hat}${pin}
      ${tier>=4?'<path d="m40 71 3 7 7 3-7 3-3 7-3-7-7-3 7-3Zm118 32 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z" fill="#e7c473" stroke="none"/>':''}
      <path d="M142 150v-14h11v14q13 19-5 22-19-3-6-22Z" fill="#d4e4dc"/><path d="M139 158q10-4 18 0" fill="none" stroke="#93b591"/>
    </g></svg>`;
  return badge?`<span class="profile-badged-avatar ${full?'badge-full':''}" data-badge-position="top-left">${drawing}<span class="profile-badge-overlay" aria-hidden="true">${badgePicture(badge)}</span></span>`:drawing;
}

function ownedHairpins(user) {
  return new Set(['none',...(Array.isArray(user.unlocked_hairpins)?user.unlocked_hairpins:[])]);
}
function profileChoices(avatar,key,choices=avatarOptions[key],locked=false) {
  return choices.map(([value,label,color])=>{
    const picture=color?`<i class="profile-color" style="background:${color}" aria-hidden="true"></i>`:profileAvatar({avatar:{...avatar,[key]:value}},{className:'profile-choice-picture',label,decorative:true,breadOnly:['face_shape','expression'].includes(key),pinOnly:key==='hairpin'});
    return `<label class="profile-choice ${locked?'profile-choice-locked':''}"><input type="radio" name="${key}" value="${value}" ${avatar[key]===value?'checked':''} ${locked?'disabled':''}><span>${picture}<b>${label}</b>${locked?`<small>${typeof locked==='string'?safe(locked):'구매 승인 후'}</small>`:''}</span></label>`;
  }).join('');
}
export function profileHairpins(user,avatar=normalizeAvatar(user.avatar,user.id)) {
  const owned=ownedHairpins(user);
  avatar={...avatar,hairpin:owned.has(avatar.hairpin)?avatar.hairpin:'none'};
  const available=avatarOptions.hairpin.filter(([id])=>owned.has(id));
  const locked=avatarOptions.hairpin.filter(([id])=>!owned.has(id));
  return `<fieldset class="profile-options" data-profile-hairpins data-unlocks="${safe(JSON.stringify([...owned]))}"><legend>구매한 빵 머리핀 <small>${available.length-1}종</small></legend><div class="profile-choices">${profileChoices(avatar,'hairpin',available)}</div>${available.length===1?'<p class="form-hint">빵 구매가 승인되면 해당 머리핀을 고를 수 있어요.</p>':''}${locked.length?`<details class="profile-locked-pins"><summary>아직 잠긴 머리핀 · ${locked.length}종</summary><div class="profile-choices">${profileChoices(avatar,'hairpin',locked,true)}</div></details>`:''}</fieldset>`;
}
export function profileBadges(user,selectedId=user.equipped_badge?.id||''){
  const badges=user.badges||[],owned=badges.filter(b=>b.owned);
  if(!owned.some(b=>b.id===selectedId))selectedId='';
  const choice=(id,name,picture)=>`<label class="badge-choice"><input type="radio" name="badge_id" value="${safe(id)}" ${selectedId===id?'checked':''}><span>${picture}<b>${safe(name)}</b></span></label>`;
  return `<fieldset class="profile-options" data-profile-badges data-badges="${safe(JSON.stringify(badges))}"><legend>내 배지 <small>${owned.length}/${badges.length}</small></legend><p class="form-hint">보유한 배지 하나를 프로필 왼쪽 위에 달 수 있어요.</p><div class="badge-grid">${choice('','배지 없음','<span class="badge-empty" aria-hidden="true">—</span>')}${badges.map(b=>b.owned?choice(b.id,b.name,badgePicture(b)):`<button type="button" class="badge-choice badge-locked" data-action="badge-info" data-badge="${safe(b.id)}" aria-label="${safe(b.name)} 배지 획득 방법"><span><i class="badge-unknown" aria-hidden="true">?</i><b>미획득 배지</b></span></button>`).join('')}</div><div class="badge-info" data-badge-info role="status" hidden></div></fieldset>`;
}
export function profileTitles(user,selectedId=user.equipped_title?.id||''){
  const titles=user.titles||[],owned=titles.filter(t=>t.owned),locked=titles.filter(t=>!t.owned);
  if(!owned.some(t=>t.id===selectedId))selectedId='';
  const choice=title=>`<label class="title-choice"><input type="radio" name="title_id" value="${safe(title?.id||'')}" ${selectedId===(title?.id||'')?'checked':''}><span>${title?profileTitle({equipped_title:title}):'칭호 없음'}</span></label>`;
  return `<fieldset class="profile-options" data-profile-titles data-titles="${safe(JSON.stringify(titles))}"><legend>내 칭호 <small>${owned.length}/${titles.length}</small></legend><p class="form-hint">보유한 칭호 하나를 이름 옆에 달 수 있어요.</p><div class="title-choices">${choice(null)}${owned.map(choice).join('')}</div>${locked.length?`<details class="locked-titles"><summary>아직 잠긴 칭호 · ${locked.length}개</summary><div class="title-choices">${locked.map(t=>`<button type="button" class="title-locked" data-action="title-info" data-title="${safe(t.id)}">${safe(t.name)}</button>`).join('')}</div></details>`:''}<div class="badge-info" data-title-info role="status" hidden></div></fieldset>`;
}
export function profileEditor(user,{onboarding=false}={}) {
  const avatar=normalizeAvatar(user.avatar,user.id);
  if(!ownedHairpins(user).has(avatar.hairpin))avatar.hairpin='none';
  if(!user.sunglasses_unlocked&&avatar.glasses==='sunglasses')avatar.glasses='none';
  const field=(key,label)=>`<fieldset class="profile-options"><legend>${label}</legend><div class="profile-choices choices-${avatarOptions[key].length} ${key==='expression'?'profile-expressions':''}">${profileChoices(avatar,key)}</div></fieldset>`;
  const glasses=`<fieldset class="profile-options"><legend>안경</legend><div class="profile-choices choices-4">${avatarOptions.glasses.map(choice=>profileChoices(avatar,'glasses',[choice],choice[0]==='sunglasses'&&!user.sunglasses_unlocked?'15점 보상 후':false)).join('')}</div></fieldset>`;
  return `<div class="profile-editor"><h2>${onboarding?'나만의 연금술사 만들기':'계정 관리'}</h2><p class="form-hint">${onboarding?'나를 닮은 빵과 작은 장식으로 꾸며요.':'꾸민 캐릭터가 내 프로필 사진으로 보여요.'}</p>
    <div class="profile-editor-preview"><div data-profile-preview>${profileAvatar({...user,avatar},{className:'profile-preview-picture'})}</div><strong class="profile-identity">${safe(user.name)}<span data-profile-title-preview>${profileTitle(user)}</span></strong><small>나의 연금술사</small></div>
    <form id="profile-editor" data-user-id="${safe(user.id)}"><div class="profile-editor-error" role="alert" hidden></div>
      <div class="profile-tabs" role="group" aria-label="캐릭터 꾸미기 종류">${[['face','얼굴'],['expression','표정'],['accessories','꾸미기'],['badges','배지'],['titles','칭호']].map(([key,label])=>`<button type="button" class="tab-chip ${key==='face'?'active':''}" data-action="profile-tab" data-tab="${key}" aria-pressed="${key==='face'}">${label}</button>`).join('')}</div>
      <div data-profile-panel="face">${field('face_shape','얼굴 종류')}${field('skin','굽기 정도')}</div>
      <div data-profile-panel="expression" hidden>${field('expression','표정')}</div>
      <div data-profile-panel="accessories" hidden>${glasses}${profileHairpins(user,avatar)}</div>
      <div data-profile-panel="badges" hidden>${profileBadges(user)}</div>
      <div data-profile-panel="titles" hidden>${profileTitles(user)}</div>
      <button type="submit" class="primary-button full profile-save">이 모습으로 저장</button>
    </form><button type="button" class="${onboarding?'text-button':'secondary-button full'} profile-editor-footer" data-action="${onboarding?'close-modal':'logout'}">${onboarding?'다음에 꾸미기':'로그아웃'}</button></div>`;
}
