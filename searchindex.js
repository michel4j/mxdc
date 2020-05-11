Search.setIndex({docnames:["analysis","api/beamlines","api/devices","api/engines","api/objects","api/purpose","api/services","chat","console","data","hutch","index","installation","overview","samples","scans","setup","starting"],envversion:{"sphinx.domains.c":2,"sphinx.domains.changeset":1,"sphinx.domains.citation":1,"sphinx.domains.cpp":2,"sphinx.domains.index":1,"sphinx.domains.javascript":2,"sphinx.domains.math":2,"sphinx.domains.python":2,"sphinx.domains.rst":2,"sphinx.domains.std":1,"sphinx.ext.intersphinx":1,sphinx:56},filenames:["analysis.rst","api/beamlines.rst","api/devices.rst","api/engines.rst","api/objects.rst","api/purpose.rst","api/services.rst","chat.rst","console.rst","data.rst","hutch.rst","index.rst","installation.rst","overview.rst","samples.rst","scans.rst","setup.rst","starting.rst"],objects:{"mxdc.Device":{add_components:[2,1,1,""],add_features:[2,1,1,""],add_pv:[2,1,1,""],cleanup:[2,1,1,""],configure:[2,1,1,""],get_pending:[2,1,1,""],is_active:[2,1,1,""],is_busy:[2,1,1,""],is_enabled:[2,1,1,""],is_healthy:[2,1,1,""],on_component_active:[2,1,1,""],set_state:[2,1,1,""],supports:[2,1,1,""]},"mxdc.Engine":{execute:[3,1,1,""],is_busy:[3,1,1,""],is_paused:[3,1,1,""],is_stopped:[3,1,1,""],pause:[3,1,1,""],resume:[3,1,1,""],run:[3,1,1,""],start:[3,1,1,""],stop:[3,1,1,""]},"mxdc.Object":{emit:[4,1,1,""],get_state:[4,1,1,""],get_states:[4,1,1,""],set_state:[4,1,1,""]},"mxdc.beamlines":{Beamline:[1,0,1,""]},"mxdc.beamlines.Beamline":{cleanup:[1,1,1,""],is_admin:[1,1,1,""],is_ready:[1,1,1,""],load_config:[1,1,1,""],setup:[1,1,1,""]},"mxdc.devices.automounter":{AutoMounter:[2,0,1,""]},"mxdc.devices.automounter.AutoMounter":{abort:[2,1,1,""],cancel:[2,1,1,""],configure:[2,1,1,""],dismount:[2,1,1,""],is_mountable:[2,1,1,""],is_mounted:[2,1,1,""],is_preparing:[2,1,1,""],is_ready:[2,1,1,""],is_valid:[2,1,1,""],mount:[2,1,1,""],prefetch:[2,1,1,""],prepare:[2,1,1,""],recover:[2,1,1,""],wait:[2,1,1,""]},"mxdc.devices.boss":{BaseTuner:[2,0,1,""]},"mxdc.devices.boss.BaseTuner":{get_value:[2,1,1,""],is_tunable:[2,1,1,""],pause:[2,1,1,""],reset:[2,1,1,""],resume:[2,1,1,""],start:[2,1,1,""],stop:[2,1,1,""],tune_down:[2,1,1,""],tune_up:[2,1,1,""]},"mxdc.devices.counter":{BaseCounter:[2,0,1,""]},"mxdc.devices.counter.BaseCounter":{count:[2,1,1,""],start:[2,1,1,""],stop:[2,1,1,""]},"mxdc.devices.detector":{BaseDetector:[2,0,1,""]},"mxdc.devices.detector.BaseDetector":{"delete":[2,1,1,""],check:[2,1,1,""],get_template:[2,1,1,""],initialize:[2,1,1,""],process_frame:[2,1,1,""],set_state:[2,1,1,""],wait:[2,1,1,""],wait_until:[2,1,1,""],wait_while:[2,1,1,""]},"mxdc.devices.goniometer":{BaseGoniometer:[2,0,1,""]},"mxdc.devices.goniometer.BaseGoniometer":{configure:[2,1,1,""],scan:[2,1,1,""],stop:[2,1,1,""],wait:[2,1,1,""]},"mxdc.devices.manager":{BaseManager:[2,0,1,""]},"mxdc.devices.manager.BaseManager":{ModeType:[2,0,1,""],align:[2,1,1,""],center:[2,1,1,""],collect:[2,1,1,""],get_mode:[2,1,1,""],mount:[2,1,1,""],wait:[2,1,1,""]},"mxdc.devices.mca":{BaseMCA:[2,0,1,""]},"mxdc.devices.mca.BaseMCA":{acquire:[2,1,1,""],channel_to_energy:[2,1,1,""],configure:[2,1,1,""],count:[2,1,1,""],custom_setup:[2,1,1,""],energy_to_channel:[2,1,1,""],get_count_rates:[2,1,1,""],get_roi:[2,1,1,""],get_roi_counts:[2,1,1,""],stop:[2,1,1,""],wait:[2,1,1,""]},"mxdc.devices.misc":{BasePositioner:[2,0,1,""],CamScaleFromZoom:[2,0,1,""],ChoicePositioner:[2,0,1,""],DiskSpaceMonitor:[2,0,1,""],Enclosures:[2,0,1,""],OnOffToggle:[2,0,1,""],Positioner:[2,0,1,""],PositionerMotor:[2,0,1,""],SampleLight:[2,0,1,""]},"mxdc.devices.misc.BasePositioner":{get:[2,1,1,""],get_position:[2,1,1,""],set:[2,1,1,""],set_position:[2,1,1,""]},"mxdc.devices.misc.CamScaleFromZoom":{get:[2,1,1,""],set:[2,1,1,""]},"mxdc.devices.misc.ChoicePositioner":{get:[2,1,1,""],set:[2,1,1,""]},"mxdc.devices.misc.DiskSpaceMonitor":{check_space:[2,1,1,""],humanize:[2,1,1,""]},"mxdc.devices.misc.Enclosures":{get_messages:[2,1,1,""]},"mxdc.devices.misc.OnOffToggle":{is_on:[2,1,1,""],off:[2,1,1,""],on:[2,1,1,""],set_off:[2,1,1,""],set_on:[2,1,1,""]},"mxdc.devices.misc.Positioner":{get:[2,1,1,""],set:[2,1,1,""]},"mxdc.devices.misc.PositionerMotor":{move_by:[2,1,1,""],move_to:[2,1,1,""],wait:[2,1,1,""]},"mxdc.devices.misc.SampleLight":{is_on:[2,1,1,""],off:[2,1,1,""],on:[2,1,1,""],set_off:[2,1,1,""],set_on:[2,1,1,""]},"mxdc.devices.motor":{BaseMotor:[2,0,1,""]},"mxdc.devices.motor.BaseMotor":{configure:[2,1,1,""],get_config:[2,1,1,""],has_reached:[2,1,1,""],is_moving:[2,1,1,""],is_starting:[2,1,1,""],move_by:[2,1,1,""],move_operation:[2,1,1,""],move_to:[2,1,1,""],on_calibration:[2,1,1,""],on_change:[2,1,1,""],on_enable:[2,1,1,""],on_motion:[2,1,1,""],on_target:[2,1,1,""],setup:[2,1,1,""],wait:[2,1,1,""],wait_start:[2,1,1,""],wait_stop:[2,1,1,""]},"mxdc.devices.shutter":{BaseShutter:[2,0,1,""]},"mxdc.devices.shutter.BaseShutter":{close:[2,1,1,""],is_open:[2,1,1,""],open:[2,1,1,""],wait:[2,1,1,""]},"mxdc.devices.stages":{BaseSampleStage:[2,0,1,""]},"mxdc.devices.stages.BaseSampleStage":{get_omega:[2,1,1,""],screen_to_xyz:[2,1,1,""],wait:[2,1,1,""],xvw_to_screen:[2,1,1,""],xvw_to_xyz:[2,1,1,""],xyz_to_screen:[2,1,1,""],xyz_to_xvw:[2,1,1,""]},"mxdc.devices.synchrotron":{BaseStorageRing:[2,0,1,""]},"mxdc.devices.synchrotron.BaseStorageRing":{beam_available:[2,1,1,""],wait_for_beam:[2,1,1,""]},"mxdc.devices.video":{VideoSrc:[2,0,1,""]},"mxdc.devices.video.VideoSrc":{add_sink:[2,1,1,""],cleanup:[2,1,1,""],configure:[2,1,1,""],del_sink:[2,1,1,""],get_frame:[2,1,1,""],start:[2,1,1,""],stop:[2,1,1,""]},"mxdc.engines.scanning":{BasicScan:[3,0,1,""]},"mxdc.engines.scanning.BasicScan":{configure:[3,1,1,""],extend:[3,1,1,""],finalize:[3,1,1,""],get_specs:[3,1,1,""],prepare_xdi:[3,1,1,""],run:[3,1,1,""],save:[3,1,1,""],scan:[3,1,1,""],setup:[3,1,1,""],start:[3,1,1,""]},mxdc:{Device:[2,0,1,""],Engine:[3,0,1,""],Object:[4,0,1,""]}},objnames:{"0":["py","class","Python class"],"1":["py","method","Python method"]},objtypes:{"0":"py:class","1":"py:method"},terms:{"17l":4,"18l":4,"abstract":[2,5],"boolean":2,"case":[8,16],"class":[1,2,3,4,8,12],"default":[1,2,3,9,17],"enum":2,"final":[0,3,14],"float":[2,3],"function":[2,7,8],"import":[2,4,7,12],"int":[2,3],"new":[0,2,3,9,14,16],"public":11,"return":[2,3,4,7,8,9],"switch":[2,13,14],"true":[1,2,4],"while":[0,2,8,9,14,15,16],CLS:12,For:[0,2,8,9,11,14,17],The:[0,1,2,3,4,7,8,9,10,12,13,14,15,16,17],Then:14,There:14,These:[4,8,9,14],Use:[0,9,14,15],XDS:9,_local:1,abl:[5,12],abort:2,about:[9,14,16,17],abov:[1,9,16],absolut:2,absorpt:15,accel:2,acceler:2,accept:[2,16],acces:[12,17],access:[0,1,4,7,11],accord:[9,15,17],accordingli:[2,3],accumul:2,acheiv:0,acquir:[0,2,3,8,9,15],acquisit:[0,2,5,8,11,14,15,16],acronym:[12,17],across:2,act:3,action:17,activ:[0,2,3,4,8,9,12,13,14,15,17],actual:[2,8,9],adapt:2,add:[0,2,3,9,15],add_compon:2,add_featur:2,add_pv:2,add_sink:2,added:[1,14,15],adding:[2,3],addit:[1,2,8,9,10,14,17],addition:12,adjust:[9,14,15,16],administr:1,adsc:9,advis:17,afresh:9,after:[1,3,8,9,17],again:9,against:0,air:14,aka:9,alarm:2,alia:[2,4],align:2,all:[1,2,3,4,8,9,13,14,16,17],allow:[2,6,8,9,14,16,17],alon:12,along:9,alow:16,alreadi:[2,9],also:[0,1,2,5,6,9,11,12,13,14,15,16,17],altern:9,although:[11,17],alwai:[9,13,14,16],amount:[2,3,8,9],analys:[0,9,14],analysi:[8,11],analyz:15,angl:[2,9,16],angular:[9,14],ani:[2,9,12,14],anim:16,anneal:14,annot:[14,15],anoth:[14,17],apertur:[14,16],api:4,append:9,appli:[9,12,16],applic:[5,7,12,13,14,16,17],appropri:[3,4,8,15],arbitrari:[14,17],archiv:[2,12],area:[9,13,14,15],arg:[2,4],arg_typ:[2,3,4],argument:[2,4,8],around:2,arrai:2,assign:8,associ:[0,9],asynchron:[0,2,3,8],attain:2,attempt:14,attenu:[9,15,16],attribut:[1,2,3,4,8,12],audienc:11,auto:14,autom:[2,14],automat:[9,14,15,17],automount:[2,17],avail:[0,2,7,8,9,10,11,13,14,15,16,17],availbl:14,avatar:7,averag:2,avoid:[8,17],awar:4,axi:[8,14],back:[0,4,9,15],backward:9,bad:[14,16],bar:[7,13,17],base:[1,2,3,4,5,7,9,11,13,14,17],basecount:2,basedetector:2,basegoniomet:2,basemanag:2,basemca:2,basemotor:2,baseposition:2,basesamplestag:2,baseshutt:2,basestorag:2,basetun:2,basic:[2,12],basicscan:3,bchi:17,beam:[9,12,13,16],beam_avail:2,beamlin:[2,3,5,7,9,11,13,14,17],beamtim:17,becam:2,becom:2,been:[1,2,7,9,11,14],befor:[2,3,8,9,14,17],behav:[2,6],behaviour:[2,14],being:9,belong:14,below:[0,2,9,14,15],berg:11,best:9,between:[2,7,9,12,13,14],bin:12,bind:5,black:11,blank:14,blconsol:[8,12],block:2,blue:16,bool:[1,2,3,4],boss:2,both:2,bottom:[7,13,14,15],bound:2,box:[13,14],bright:9,browser:0,built:2,bulk:9,busi:[2,3],button:[0,9,13,14,15,16,17],calcul:[0,2,9,14,15],calibr:2,call:[1,2,3,8],callback:[2,4],camera:[2,16],camscalefromzoom:2,can:[0,1,2,3,4,6,7,8,9,11,12,13,14,15,16,17],canadian:11,cancel:2,capabl:[5,8,14],capillari:14,care:2,carri:14,cartographi:[9,14],caus:16,cbf:9,cell:[12,14],cema:8,center:[2,14,16],central:1,certain:13,chang:[2,9,14,16,17],channel_to_energi:2,chat:11,check:[1,2,3,14,16],check_spac:2,checkbox:14,children:2,choic:2,choiceposition:2,chooch:15,choos:9,circl:14,clean:[1,2],cleanup:[1,2],clear:[2,9,14],click:[0,9,14,15,16,17],client:6,close:[2,4,17],cmcfbm:17,code:7,collect:[2,9,14],collector:11,color:[7,9,14,16],column:[8,9,14],combin:[2,8,9],come:4,command:[2,4,5,8,9,11,13,16],commiss:8,common:[2,3],commun:7,compar:2,compat:2,complet:[0,2,3,8,9,14,15],complex:5,compon:[1,2,4,13,16],compos:7,compress:8,confid:15,confidenti:17,config:[1,3,12],config_exampl:12,configur:[0,1,2,3,8,9,11,14,15,17],conjunct:14,connect:[4,6],consider:9,consist:[16,17],consol:[1,11,12],constant:9,construct:2,consult:11,contain:[2,3,12,14,17],context:[2,16,17],contigu:9,continu:[2,8,9,14],control:[0,2,5,8,9,11,12,14,15,16],convei:16,conveni:[1,2,14],convent:1,convert:[2,3],cool:2,coordiant:2,coordin:[2,9],copi:[4,9,12],corner:[14,16],correspond:[0,2,4,9,14],count:2,countdown:14,counter:[3,8],coupl:14,creat:[2,3,4,5,8,9,12,14],criteria:14,critic:2,cross:16,crosshair:14,cryogen:14,crystal:14,crystallographi:11,ctrl:[0,14,17],current:[0,1,2,3,8,9,13,14,15,16,17],cursor:14,curv:8,custom:[2,7],custom_setup:2,cycl:[9,14],daemon:3,dark:2,data:[2,3,5,6,11,12,14,15,16,17],databas:14,dataset:[0,2,9,15,17],date:17,dcm_pitch:8,dead:2,deadtim:2,declar:6,def:4,defin:[1,4,9,12,14,16],deg:12,degre:[9,14],dehydr:14,del_sink:2,delet:[2,9],delta:9,depend:[2,9,12,14,15],deploi:12,deriv:[2,3],descr:2,describ:[3,9,11],descript:[2,16],deselect:[9,14],design:2,desir:[0,2,8,12,15],desktop:5,destin:12,destroi:8,destruct:8,detail:[2,3,4,9,17],detector:[9,16],determin:[2,9],develop:11,develp:11,devic:[1,3,6,8,11,12,14],diagnos:16,diagnost:13,dialog:[9,15],dict:1,dictionari:[2,3,4,12],differ:[4,9,11,13],diffract:[10,12,14],diffractomet:2,dimens:14,dimension:9,direct:[9,14],directi:2,directli:[1,2,9],directori:[2,9,12],disabl:[2,14],discourag:3,disk:2,diskspacemonitor:2,dismount:[2,14],displai:[0,7,8,9,10,13,14,15,16],distanc:[9,16],distinguish:14,distribut:12,divid:[0,7,9,11,15],docstr:8,doi:11,doing:6,done:[2,3],door:4,doubl:[14,17],doubt:16,down:[0,2,9,14,16],drag:9,draw:[9,14],drawn:14,drive:12,driven:5,drop:[9,14,16],due:4,dummi:2,durat:[2,14],dure:14,each:[2,9,12,13,15,16,17],earlier:11,easier:14,edit:9,editor:9,effect:9,either:[0,9,17],element:[2,15],els:4,email:7,emiss:4,emit:[2,4],empti:14,enabl:[2,9,14],enclos:[2,14],enclosur:[2,16],end:[2,3,8,14],energi:[2,9,15,16],energy_to_channel:2,engin:[6,11],enhanc:8,enter:16,entri:[2,7,14,15,16],enumer:2,environ:[2,5,12,14,17],epic:[2,5],equip:14,error:[0,3,16],essenti:16,etc:[2,9],evalu:9,even:2,event:[4,5],event_nam:4,everi:2,everytim:[2,9],exact:[16,17],exactli:9,exampl:[1,2,3,4,8,9,12,17],except:[2,8,12],excit:15,execut:[3,8,17],exhaust:2,exist:[2,7,9],exit:8,expect:[2,9,12,14],experi:[5,9,11,14,16,17],experiment:[10,16],explicitli:2,exposur:[2,9,14,15],extend:[3,8,11],extens:[9,11],extern:[6,14],facil:12,fact:14,fail:2,failur:2,fals:[1,2,4],familiar:14,fast:[2,13],faster:14,fbk_name:2,featur:[2,4,7,8,9,10,14],feeback:13,feed:[15,16],feedback:[2,13,16],fetch:[2,6,14,17],few:[10,12],field:[3,9],file:[1,2,3,8,9,12,17],filenam:3,fill:14,filter:14,finger:14,first:[2,8,9,14],fix:9,flag:2,flow:14,fluoresc:[2,15],flux:[13,14],focu:14,focus:13,fodj:[11,17],follow:[1,2,3,4,8,9,11,12,17],forbidden:4,forc:2,form:9,format:[2,4,9,12],forward:[0,9],four:14,fraction:[2,3],frame:[2,9],framework:[5,11],freez:14,freq:2,frequenc:2,friendli:2,from:[1,2,3,4,7,8,9,12,13,14,15,16,17],full:[3,9,12,17],fulli:2,fundament:4,further:15,fwhm:8,fwhm_hist:8,gaussian:8,gener:[2,3,11,12,16],gestur:9,get:[2,3,4,8,11],get_config:2,get_count_r:2,get_fram:2,get_messag:2,get_mod:2,get_omega:2,get_pend:2,get_posit:2,get_roi:2,get_roi_count:2,get_spec:3,get_stat:4,get_templ:2,get_valu:2,gio:5,give:17,given:[0,2,3,9,14,17],glib:5,global:[1,9,13],gnome:5,gobject:[4,5],goe:2,goniomet:[12,14,16],good:16,gorin:11,graphic:5,green:16,grid:[9,14],grochulski:11,group:[9,14,17],gtk3:4,gtk:5,gui:[4,5,8,11,12],gzip:8,hand:[14,16],handl:4,hardwar:2,has:[2,9,11],has_reach:2,have:[1,7,9,14,15],hdf5:[2,9],header:[7,9,13,17],health:2,helic:2,help:[8,13],helper:2,here:[1,12],hhmmss:8,high:[2,15],higher:5,highest:14,highli:9,highlight:14,hold:[0,14],horizont:[2,9],hover:14,how:[4,9,17],howev:[9,14],html:0,http:11,hub:1,human:2,humid:9,hutch:[7,11,12],hutchview:12,hyphen:4,icon:[7,9,14,16,17],ident:14,identifi:[9,13,14,15],idl:2,ignor:[2,9],illumin:2,imag:[2,10,12,14,15,16,17],imgview:12,immedi:14,imotor:2,implement:[2,3],inact:2,includ:[2,3,8,9,12,14,16,17],increment:14,index:9,indic:[2,9,14,15],individu:[2,9,14],inform:[2,9,11,13,14,17],init:8,initi:[0,1,2,9,14,15],input:2,insid:16,inspect:16,instal:[11,17],instanc:[2,8,12,17],instant:7,instanti:2,instead:3,integr:[2,5,9],intens:[2,9],interact:[0,2,14,15],interest:[2,11,15],interfac:[2,10,11],interleav:9,intern:4,interv:14,introspect:8,invers:9,investig:8,involv:3,ipython:[4,8],is_act:2,is_admin:1,is_busi:[2,3],is_en:2,is_healthi:2,is_mount:2,is_mov:2,is_on:2,is_open:2,is_paus:3,is_prepar:2,is_readi:[1,2],is_start:2,is_stop:3,is_tun:2,is_valid:2,issu:16,ital:14,item:4,its:9,ivideosink:2,janzen:11,just:2,kei:[0,2,4,7,14],kev:2,keyboard:14,keyword:[2,3],known:9,korea:11,kwarg:[2,3,4],label:[13,14],labiuk:11,larg:14,last:2,later:[4,8],launch:[8,12],layout:[2,14],learn:[8,14],left:[0,7,9,13,14,15,16],length:12,level:[2,5,12,14,17],librari:5,light:[2,11,14],like:[2,5,6,8,9,17],lim:6,limit:[12,17],line:[5,8,9],link:[2,9],linux:5,liquid:14,list:[1,2,3,4,9,16],listenn:2,live:[8,13],load:[1,2,9,14],load_config:1,local:1,locat:[0,9,14,15,17],lock:4,log:[11,14,17],longer:17,look:17,loop:[3,4,14],lorentz:8,lost:9,machin:14,macromolecular:11,mad:[0,9,17],made:[0,14],magic:4,mai:[5,9,12,13,15,16],main:[4,12,13,15],maintain:2,make:[2,9,17],manag:[3,8,11,12,14],mandatori:12,mani:[2,5,12],manipul:[2,9,15],manner:9,manual:14,map:12,marccd:9,margin:2,mark:[9,14],max:[2,15],maxfp:2,maximum:[2,9,14],mca:2,meaning:9,measur:15,mechan:[1,2,6,7],meet:14,menu:[16,17],merg:0,messag:[2,3,4,7,8],meta:[2,6],method:[1,2,3,7,8,9,14],microscop:[2,9],middl:9,midp:8,midp_hist:8,might:17,minimum:2,minor:2,minu:14,minut:2,misc:2,miscroscop:9,mmm:8,mode:[9,13,14,15],modetyp:2,modifi:[12,14],modul:[1,12],moment:17,monitor:[2,3],mono:12,mono_unit_cel:12,monochrom:12,more:[2,5,8,9],most:[2,8,12,15,16],motion:16,motor:[3,8,12,16],mount:[0,2,9,14,17],mous:[9,14],move:[2,7,9,14,16,17],move_bi:2,move_oper:2,move_to:2,much:9,multi:3,multichannel:2,multipl:[0,3,4,9,14],must:[1,2,3,12],mxbeamlin:12,mxdc:[1,2,3,4,5,6,7,8,9,10,11,12,13,15],mxdc_config:12,mxlive:[11,14],mxn:2,name:[0,1,2,3,4,8,9,12,14,17],navig:9,neccessarili:4,necessari:0,necessarili:14,need:[1,2,3,6,12,17],network:5,newli:14,next:[2,9,14],next_port:2,nice:5,nitrogen:14,non:[2,4,8],none:[2,3,8],normal:[3,8],note:[9,17],notifi:3,now:9,nozzl:2,number:[2,4,9,14,15],obj:[2,4],object:[1,2,3,6,8,11,12],obtain:[2,4,9],off:[2,13],offset:9,often:[14,17],omega:[2,12,14,16],on_calibr:2,on_chang:2,on_component_act:2,on_en:2,on_lock:4,on_mot:2,on_open:4,on_target:2,onc:[8,9,14,15,17],one:[2,8,9,17],onli:[2,7,9,10,12,14,16,17],onoff_nam:2,onofftoggl:2,onto:2,open:[2,4,9],oper:[2,3,5,9,12,13,14,16,17],opert:14,optim:2,option:[1,2,3,8,9,14],orang:16,order:[0,2,9],org:11,organ:[9,13,17],organis:17,other:[2,4,5,8,9,14],otherwis:[2,9],our:2,out:[2,4,14,17],output:[2,17],outsid:[8,16],over:[2,9],overal:13,overlai:14,overlaid:[8,9],overrid:3,overridden:2,overview:11,overwrit:9,overwritten:9,packag:11,page:[0,9,10,14,15],pair:[2,3,4,9],pan:[9,16],param:[2,8],paramet:[1,2,3,4,8,14,15,17],partial:9,pass:2,path:[2,3],pattern:9,paus:[2,3,9,14],pausabl:3,peiod:2,pend:[0,2,9],per:[2,9],percent:2,percentag:[2,9,14],perform:[0,2,5,9,12,14,15],period:[2,15],person:7,perspect:2,philosophi:12,phone:7,physic:14,pil:2,pixel:[2,9],place:12,plan:17,plot:[8,12,14],plotxdi:[8,12],plu:[2,14],png:9,pohang:11,point:[2,3,9,12,14],pointer:14,poll:2,popup:15,port:[2,14,17],portabl:12,portion:9,pos:2,posit:[2,8,9,14,16,17],position:[2,8],positionermotor:2,possibl:[2,16,17],powder:9,pre:[2,14,16],precend:2,precis:[2,12],prefer:[9,17],prefetch:[2,14],prefix:2,prepar:[2,3],prepare_xdi:3,present:17,preserv:9,press:[7,14],pressur:2,previou:[2,9,15],previous:[8,9],primari:[0,9,11,15],primarili:11,print:4,prior:[9,14],prioriti:[9,14],problem:16,proce:16,proceed:[9,14],process:[2,14],process_fram:2,produc:[2,17],profil:9,program:[12,17],progress:[0,2,3,8,9,13],prompt:[8,9],proper:6,properli:14,properti:[2,4],provid:[1,2,3,4,5,7,8,9,10,12,13,14,16],pseudo:9,purpos:11,push:6,pv_name:2,pygobject:5,python3:12,python:[1,2,5,8,12],queri:2,queue:9,quickli:16,quit:17,rad:11,rai:15,rais:2,rang:[2,8,9],raster:[2,14,17],rate:[2,9,14],rather:[7,9,14],raw:2,reach:2,read:1,readi:[0,1,2,4],realtim:8,reason:3,receiv:2,recent:[2,8],recollect:9,recommend:[9,11,12,14],record:2,recov:2,red:[14,16],refer:[3,8],reflect:14,refresh:14,region:[0,2,7,9,15],regist:[1,4,8],registr:4,registri:1,rel:[2,14],relat:[11,17],releas:14,relev:[2,17],reli:17,reliabl:16,reload:0,relscan:8,remain:14,remot:[11,16],remov:[2,9],repeat:14,replac:[4,7,15],report:[2,3],repres:[2,3],represent:[2,9],request:[0,2,9,16],requir:[1,2,3,4,8,14],reset:[2,9,14],resolut:[9,14],restrict:12,result:[0,2,3,8,9,14,15],resum:[2,3,9],right:[0,7,9,13,14,15,16],ring:13,robot:2,roi:2,room:14,rotari:2,rotat:14,row:[0,3,9,14],run:[0,1,3,7,8,9,12,15,17],s0909049511056305:11,safe:4,sai:0,sam:14,same:[2,9,12,14],sampl:[0,2,9,10,11,12,17],sample_x:12,sample_y1:12,sample_y2:12,samplelight:2,save:[3,9,12,14,15,17],scale:2,scan:[2,3,9,11,14,17],score:[0,14],screen:[0,2,9],screen_to_xyz:2,screenshot:[8,13,14,16],script:[8,12],scroll:[9,14],search:14,second:[2,14],section:[11,12],see:[9,12],select:[0,7,8,9,14,15,16],send:2,sent:17,separ:7,sequenc:[2,3,9,17],seri:2,seriou:2,server:[0,6],servic:[1,11,12,14],session:[14,17],set:[2,3,4,14,15,17],set_nam:2,set_off:2,set_on:2,set_posit:2,set_stat:[2,4],setup:[1,2,3,10,11,12,14],sever:[2,4,15],sgu:12,shadow:8,shell:[4,8],shift:0,shipment:17,shortcut:8,should:[1,2,3,8,9,11,12,14,17],show:[8,9,13,14,16],shown:[14,16],shutdown:2,shutter:13,shutterless:2,side:17,signal:[1,2,3,4,6],signatur:[2,8],significantli:17,sim:[8,12],simgonio:12,similar:[2,12],similarli:0,simmodemanag:12,simmotor:12,simpl:[0,2,7],simpli:[2,9],simplifi:10,simul:[8,12],simultan:4,sinc:[3,11,12,14],singl:[2,8,9,14,17],sink:2,site:14,size:[2,9,14],slew:8,slewscan:8,slice:9,slider:14,smv:9,snapshot:9,softwar:[5,11],solut:5,some:[2,3,8,9,14,16],sometim:8,soon:14,sourc:[2,11,12],south:11,space:2,spawn:3,special:12,specif:[2,3,4,8,9,12,13,14,17],specifi:[2,8,9,12,17],spectroscop:15,spectroscopi:15,speed:[2,8,12,14],spot:9,squar:16,staff:[7,11,16,17],stand:12,standard:5,standbi:2,start:[2,3,8,9,11,14,15],state:[0,2,3,4,9,13,14,16],station:2,statu:2,step:[2,8,9],stop:[0,2,3,8,9,14,16],stoppabl:3,storag:17,store:[2,17],str:[2,3,4],strategi:[0,9,15],stream:14,string:[2,3,4,12,17],strongli:17,structur:17,sub:[2,3,12],subclass:[2,3,4],submit:[0,7],subnet:[12,17],subsequ:9,subset:2,substitut:[2,17],success:2,successfulli:2,suffici:14,suitabl:[2,10,15],supplement:7,support:[2,4,8,9,14],sure:[2,9],switcher:13,synchron:[12,14],synchrotron:[2,11,12,13],system:[2,4,5,6,11,12,17],tabl:[2,9,15],take:[2,8,9],taken:2,target:[2,11,14],task:[1,9],techniqu:11,temperatur:[2,14],templat:[2,9,17],temporari:14,term:14,termin:[2,17],test:[8,17],text:[14,16],than:[2,7,9,14],thei:[2,9,12],them:[2,4,8],therefor:[2,14,16],theta:16,thi:[0,1,2,3,4,7,8,9,12,14,15,16,17],those:2,thread:[3,4],three:11,through:[4,8,9,12,14,17],thu:9,tiff:9,tilt:16,time:[2,9,13,14,15],timeout:2,timestamp:2,tip:14,togeth:10,toggl:[2,9,15],tool:[9,12,15],toolbar:[9,14],top:[9,12,13,14,15,16,17],total:[2,9],tradit:[6,8],transform:4,translat:[2,4],trash:9,travel:8,tree:0,tri:4,trigger:[2,4],tunabl:2,tune:14,tune_down:2,tune_up:2,tupl:[2,3],turn:2,tweak:2,twist:5,two:[0,4,7,9,15,16],type:[0,2,3,4,8,9,11,12,13,14,17],typic:[12,17],underscor:4,uniqu:[9,17],unit:[2,12,14],unknown:16,unless:9,until:[2,14],updat:[0,2,3,8,9,14,15],usabl:[4,17],usag:[8,12],use:[6,8,9,14,15,17],used:[0,2,8,9,11,13,14,15,17],user:[1,7,8,9,11,14,16,17],uses:17,using:[0,2,4,7,8,9,11,12,14,15,16,17],usual:[9,14,16],util:3,vacuum:2,val:2,valid:[2,9,12],valu:[1,2,3,4,9,14,15,16,17],vari:[15,16],variabl:[1,2,3,12,17],variant:[2,12],varieti:9,variou:[8,12,16],vector:[2,9],venv:12,veri:9,version:[9,10,11,15],vertic:2,vial:14,video:[9,10,14],videosrc:2,view:[0,7,9,13,14,15,16],viewer:[11,12],virtual:12,visibl:[13,14],visual:5,voigt:8,voltag:2,wait:2,wait_for_beam:2,wait_start:2,wait_stop:2,wait_tim:2,wait_until:2,wait_whil:2,want:[5,9,14],warn:[2,16,17],watcher:3,websit:6,wedg:9,well:[1,17],were:[9,15],when:[0,2,3,7,9,14,17],whenev:9,where:[2,8,9,14,16],whether:[2,9,13],which:[1,2,3,4,5,6,8,9,11,12,14,15,16,17],wich:14,width:2,window:[2,8,13,17],within:[9,12,14,17],without:[2,8,17],word:2,would:12,wrap:3,written:5,xdi:[3,8,12],xdi_data:3,xvw_to_screen:2,xvw_to_xyz:2,xxxxxx:8,xyz_to_screen:2,xyz_to_xvw:2,yet:2,ymax:8,ymax_hist:8,you:[1,5,6,8,9,12,14,15,17],your:[12,14,17],yourself:14,yyyi:8,zoom:[2,9,14,16]},titles:["Analysis","Beamlines","Devices","Engines","Objects","Purpose","Services","Chat and Log","Beamline Console","Data","Hutch Viewer","MxDC - Macromolecular Crystallography Data Collector","Installation","Overview","Samples","Scans","Setup","Getting Started"],titleterms:{"default":8,Use:11,XAS:15,acquisit:9,acquitis:9,all:12,analysi:0,analyz:2,auto:2,autom:9,automount:14,avail:12,beam:[2,14],beamlin:[1,8,12,16],channel:2,chat:7,command:12,configur:12,consol:8,counter:2,creat:17,cryo:14,data:[0,8,9],detector:2,devic:[2,16],diffract:9,directori:17,document:11,edg:15,engin:3,environ:8,fit:8,get:17,goniomet:2,how:11,humid:14,hutch:[10,16],imag:9,index:11,instal:12,integr:17,interact:9,interfac:13,list:14,log:7,mad:15,manag:2,microscop:14,miscellan:2,mode:2,motor:2,mounter:2,multi:2,mxdc:17,mxlive:17,object:4,overview:13,panel:13,paramet:[9,12,16],perform:8,plot:15,purpos:5,raster:9,report:0,requir:12,ring:2,sampl:14,save:8,scan:[8,15],selector:15,servic:6,set:9,setup:16,shutter:2,stage:2,start:17,statu:[13,16],stop:17,storag:2,tabl:0,thi:11,tool:[7,14],tuner:[2,14],user:13,video:[2,16],viewer:[0,7,9,10],xrf:15}})