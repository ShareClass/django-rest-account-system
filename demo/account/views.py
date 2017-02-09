import hashlib
import datetime
import time
import uuid

from django.core.validators import validate_email
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError 
from django.core.mail import send_mail
from django.shortcuts import render
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view
        
from .models import UserProfile, ResetPasswordToken



# 這個 Method 是用來測試查看使用者登入狀況
@api_view(['GET'])
def get_user_info(request):
    if not request.user.is_authenticated():
        return Response({"auth":"Anonymous user"}, status=200)
        
    user = request.user
    return Response({"username":user.username, "email": user.email},
            status=status.HTTP_200_OK)

        



@api_view(['GET', 'POST'])
def sign_in(request):
    if request.user.is_authenticated():
        return Response({"error":"already_login"}, status=status.HTTP_400_BAD_REQUEST)
    
    # handle GET method
    if request.method != "POST":
        return render(request, "login.html")
   
    try:
        username = request.data["username"]
        password = request.data["password"]
    except KeyError:
        return Response({"error": "請輸入username, password"},
        status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return Response({"error": "不存在這個使用者"},
        status=status.HTTP_401_UNAUTHORIZED)
    else:
        if user.social_auth.exists():
            return Response({"error":"Oauth Account, 請使用 Oauth 登入"},
            status=status.HTTP_403_FORBIDDEN)

    user = authenticate(username=username, password=password)
    if user is None:
        return Response(status=status.HTTP_401_UNAUTHORIZED)
     
    login(request, user)
    
    return Response(status=status.HTTP_200_OK)
        


# TODO 為了測試方便有設定允許 GET, 但是實際上不行
@api_view(['GET', 'POST'])
def sign_out(request):
    if not request.user.is_authenticated():
        return Response({"error": "使用者尚未登入"},
        status=status.HTTP_401_UNAUTHORIZED)

    logout(request)
    return Response(status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
def general_sign_up(request):
    # Django User Model 只有保證 username 是 unique 這件事情
    if request.user.is_authenticated():
        return Response({"error":"使用者已登入"},
        status=status.HTTP_400_BAD_REQUEST)
    
    if request.method != "POST":
        return render(request, "register.html")


    ### The following is for handing POST method 
    print(request.data)
    try:
        username = request.data["username"]
        email = request.data["email"]
        password = request.data["password"]
        confirm_password = request.data["confirm_password"]
    except KeyError:
        return Response({"error": "欄位尚未填寫完整"},
        status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    # TODO username format validation

    # check uniqueness of username
    exist_username = User.objects.filter(username=username).exists()
    if exist_username:
        return Response({"error":"Username 已被註冊"},
        status=status.HTTP_409_CONFLICT)
    
    # email format validation 
    try:
        validate_email(email)
    except ValidationError:
        return Response({"error":"email_format_error"},
        status=status.HTTP_400_BAD_REQUEST)

    # check uniqueness of email
    exist_user_email = User.objects.filter(email=email).exists()
    if exist_user_email:
        return Response({"error":"Email 已被註冊"},
        status=status.HTTP_409_CONFLICT)
    
    # TODO password format validation
    
    # password confirm validation
    if password != confirm_password:
        return Response({"error":"password_confirmation_failed"},
        status=status.HTTP_400_BAD_REQUEST)
    
    # create user
    user = User(username=username, email=email)
    user.set_password(password)
    user.save()
    
    return Response(status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
def change_password(request):
    if not request.user.is_authenticated():
        return Response(status=status.HTTP_401_UNAUTHORIZED)
     
    if request.user.social_auth.exists():
        return Response({"error": "Oauth 帳戶不能修改密碼"}, 
        status=status.HTTP_403_FORBIDDEN)

    # handle GET method 
    if request.method != "POST":
        return render(request, "change_password.html")

    try:
        current_password = request.data['current_password']
        new_password = request.data['new_password']
        confirm_new_password = request.data['confirm_new_password']
    except KeyError:
        return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
   
    user = request.user
    if not user.check_password(current_password):
        return Response({"error":"與目前密碼不符"},
        status=status.HTTP_400_BAD_REQUEST)

    if new_password != confirm_new_password:
        return Response({"error":"password_confirmation_failed"},
        status=status.HTTP_400_BAD_REQUEST)

    # TODO password format validation
    
    
    user.set_password(new_password)
    user.save()

    return Response(status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
def find_password(request):
    # missing password 要填的資料: email
    # 填完後送出後，會寄一封信件給 user, 內容夾帶著 reset password
    # 的連結。
    
    # handle GET method
    if request.method != "POST":
        return render(request, "find_password.html") 

    try:
        email = request.data['email']
        validate_email(email)
    except KeyError:
        return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except ValidationError:
        # 必須要 validate 因為 facebook 不一定能夠取得 email
        # 會造成多個 email == "" 的情況，後面的 User.objects.get
        # 就不能使用了
        return Response({"error":"email_format_error"},
        status=status.HTTP_400_BAD_REQUEST)

    user_exist = User.objects.filter(email=email).exists()
    if not user_exist:
        return Response(status=status.HTTP_403_FORBIDDEN)
    
    user = User.objects.get(email=email)
    if user.social_auth.exists():
        return Response({"error":"Oauth user"}, status=status.HTTP_403_FORBIDDEN)
    
    # generate reset password url
    url_seed = (email + time.ctime() + "#$@%$").encode("utf-8")
    url_token = hashlib.sha256(url_seed).hexdigest()

    entry_token_seed = str(uuid.uuid1()).encode("utf-8")
    entry_token = hashlib.md5(entry_token_seed).hexdigest()[10:16]
    
    current_time = timezone.localtime(timezone.now())
    accessible_time = current_time + datetime.timedelta(minutes=10)
    
    rt = ResetPasswordToken.objects.get(user=user)
    rt.dynamic_url = url_token
    rt.entry_token = entry_token
    rt.expire_time = accessible_time
    rt.save()

    # Send Email Message
    email_content = "Hi, {username}\n\
已下是重置密碼的連結，如果您沒有使用忘記密碼的功能，請忽略本信\n\
下面的連結存活時間到 {expire_time} 為止。\n\n\
{reset_password_url}\n\
另外，在該連結中必須輸入Token: {entry_token}, 用以驗證。\n\n\
感謝您的使用!\n\n\n\
From service@shareclass.com".format(username=user.username,
            reset_password_url="http://127.0.0.1:8000/accounts/reset_password/" + url_token,
            expire_time=accessible_time.strftime("%Y-%m-%d %H:%M"),
            entry_token=entry_token)

    print(email_content)

    send_mail(
            'Share Class 忘記密碼重置信',
            email_content,
            'service@jielite.tw',
            [email],
            fail_silently=False,
    )    
     
    return Response(status=200)
        

@api_view(['GET', 'POST'])
def reset_password(request, url_token):
    # 設定成功之後，沒有限制操作次數

    # 不讓已登入的人來找密碼
    if request.user.is_authenticated():
        return Response(status=status.HTTP_400_BAD_REQUEST)

    if request.method != "POST":
        return render(request, "reset_password.html")
    
    # Dynamic URL Token Validation
    try:
        user_reset_password_token = ResetPasswordToken.objects.get(dynamic_url=url_token)
    except ResetPasswordToken.DoesNotExist:
        return Response(status=status.HTTP_403_FORBIDDEN)
    
    # check Dynamic URL lifetime
    if timezone.now() > user_reset_password_token.expire_time:
        return Response(status=status.HTTP_403_FORBIDDEN)

    # Request Data Validation 
    try:
        new_password = request.data['new_password']
        confirm_new_password = request.data['confirm_new_password']
        entry_token = request.data['entry_token']
    except KeyError:
        return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    else:
        if new_password != confirm_new_password or\
        entry_token != user_reset_password_token.entry_token:
            return Response({"error":"輸入不一致或是驗證碼錯誤"},
            status=status.HTTP_400_BAD_REQUEST)
    
    # TODO Password Validation


    # Reset Password
    user = user_reset_password_token.user
    user.set_password(new_password)
    user.save()

    return Response(status=status.HTTP_200_OK)