name = "Manish"
upper = name.upper()
length = len(name)
print(length)
print(name[1:3])
print("m" in name)
print("M" in name)
l = [1, 2, 3, 4, 5]
print(l)
l.pop()
print(l)
a = l.pop()
print(a)
print(l)
l = ["manish", "cs"]
for i in enumerate(l):
    print(i)
for i in range(1,11):
    for j in range(1,11):
        print(f"{i} X {j} = {i*j}")
    print()
l = [1,23,43,534,32]
total = 0
for i in l:
    total += i
print(total)
print([i*2 for i in l if i % 2== 0])
print([i*2 for i in range(1,11) if i % 2 == 0])
a = "abc$43"
print(a.isalnum())
# i = [int(n) for n in input("i> ").split()]
# sum=0
# for j in i :
#     sum+= j
# print (i,sum)
d = {
    "name" : "manish",
    "age" : 17,
    "add" : "banglure"
}
dl = {key:val for key,val in d.items()}
print(d,dl)
l = [1, 2 ,3, 4, 5, 6, 7, 8, 9, 0]
print((100*101)/2)
t = 0
for i in range(1,101):
    t += i
print(t)
class a():
    def __init__(self, name , age):
        self.__name = name
        self.age = age
    def display(self):
        print(f"name : {self.__name} \nage : {self.age}")
m = a("manish", 17)
m.display()
class b(a):
    def edit(self,name,age):
        self.__name = name
        self.age = age
mm= b("man", 16)
mm.display()
mm.edit("mmm",11)
mm.display()
